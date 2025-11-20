import json
import sys

from sympy import symbols, Matrix, nsolve, diff, sqrt

# transmission power in dBm
P = 16.0

def rssi_to_distance(rssi):
    return (10 ** ((P - rssi) / 20)) / 100.6

def mlat(data):
    """
    Solve for transmitter (X, Y, Z) given:
        data = {
            # anchor locations
            'x': [[x1,y1,z1], [x2,y2,z2], ...],
            # anchor RSSI in dBm
            'r': [r1, r2, ...]
        }
    """
    # extract receiver coordinates and RSSI
    Rx = Matrix(data['x'])
    rssi = data['r']
    N = len(rssi)
    if Rx.shape[0] != N or Rx.shape[1] != 3:
        raise ValueError("x must be Nx3 and r must be length N")

    # convert RSSI to distances
    d = [rssi_to_distance(ri) for ri in rssi]

    # unknown transmitter coordinates
    X, Y, Z = symbols('X Y Z', real=True)

    # residuals: sphere equations
    residuals = []
    for i in range(N):
        xi, yi, zi = Rx[i, 0], Rx[i, 1], Rx[i, 2]
        di = d[i]
        residuals.append((X - xi)**2 + (Y - yi)**2 + (Z - zi)**2 - di**2)

    # initial guess: centroid of receivers (good heuristic)
    cx = sum(Rx[i,0] for i in range(N)) / N
    cy = sum(Rx[i,1] for i in range(N)) / N
    cz = sum(Rx[i,2] for i in range(N)) / N
    initial_guess = (float(cx), float(cy), float(cz))

    # least-squares: minimize sum(residual_i^2)
    f = sum(r**2 for r in residuals)
    grad_eqs = [diff(f, X), diff(f, Y), diff(f, Z)]
    sol = nsolve(grad_eqs, (X, Y, Z), initial_guess, tol=1e-12, maxsteps=100)

    return [float(sol[0]), float(sol[1]), float(sol[2])]

if __name__ == "__main__":
    '''
    Example data:
        '{ "x": [[100, 100, 50], [200, 100, 50], [100, 200, 50]], "r": [-66.6891, -63.6799, -63.6799] }'
    '''

    data = json.loads(sys.argv[1])

    tx = mlat(data)

    print(json.dumps(tx))

