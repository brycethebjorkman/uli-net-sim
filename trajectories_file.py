import xml.etree.ElementTree as xml
from pathlib import Path


def validate_drones() -> int:
    while True:
        try:
            num = int(input("Number of Drones: "))
            if(num < 1):
                print("Please enter a number above 0")
                continue
            else:
                return num 
        except ValueError:
            print("Please enter a valid number")
            continue
        except TypeError:
            print("Please enter an integer")
            continue

def get_drone_data(num_drones: int) -> dict:
    print("---Construct each Drone---")
    num_of_waypts = 0
    while True:
        try:
            num_of_waypts = int(input("Number of Waypoints (not including initial position): "))
            if(num_of_waypts < 1):
                print("Please enter a number above 0")
                continue
            else:
                break 
        except ValueError:
            print("Please enter a valid number")
            continue
        except TypeError:
            print("Please enter an integer")
            continue


    drones = {}
    list_of_waypts = []
    
    for i in range(num_drones):
        name = f"{i}"
        match(i):
            case 0:
                name = "Control"
            case 1:
                name = "Spoof"
            case 2:
                name = "Ego"
        
        for j in range(num_of_waypts+1):
            
            pos_input = input(f"Enter position {j} for {name} drone (ft) (x y): ")
            pos=pos_input.split()
            
            if len(pos) != 2:
                continue
                
            try:
                values = [float(v) for v in pos]
                list_of_waypts.append(values)
                
            except ValueError:
                print("all values must be floats")
        print()
        drones[name] = list_of_waypts
        list_of_waypts = []
            
    return drones



def make_xml(drones: dict):
    print("---Make XML file---")
    root = xml.Element('turtle_mobility')
    tree = xml.ElementTree(root)

    for key, val in drones.items():
        movement = xml.Element('movement')
        movement.set("name", f"{key}")
        
        set_comp = xml.Element('set')
        set_comp.set('x',f'{val[0][0]}') # get initial position of first drone
        set_comp.set('y', f'{val[0][1]}')
        
        
        movement.append(set_comp)
        for i in range(1, len(val)):
            moveto = xml.Element('moveto')
            moveto.set('x',f'{val[i][0]}')
            moveto.set('y',f'{val[i][1]}')
            movement.append(moveto)
        root.append(movement)
    i = 0
    while True:
        if Path(f"turtles_mobility ({i}).xml").is_file() == False:
            
            xml.indent(tree, space=" ", level = 0)
            print(xml.tostring(root))
            tree.write(f"turtles_mobility ({i}).xml", encoding="utf-8", xml_declaration=True)
            break
            
        i = i+1


    
    

def main():
    num_drones = validate_drones()

    drones = get_drone_data(num_drones)
    print(drones)
    make_xml(drones)

if __name__ == "__main__":
    main()
# trajectories_file.py