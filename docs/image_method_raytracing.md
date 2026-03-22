# Image Method Raytracing Propagation Model

This document describes the raytracing-based multipath propagation model
implemented in `src/propagation/ImageMethodObstacleLoss.cc`.

## Motivation

INET's built-in `DielectricObstacleLoss` computes signal attenuation along
the direct line-of-sight (LOS) path only.  When LOS is blocked by a
building, the signal is attenuated by dielectric penetration loss — but
no alternative propagation paths are considered.  In real urban
environments, reflected signals (off building walls, roofs, and the
ground) can provide significant received power even when LOS is fully
obstructed.  This multipath effect is critical for realistic RSSI
modelling in our spoofing detection research, because the detectors use
RSSI–distance consistency as a primary feature.

The `ImageMethodObstacleLoss` module replaces `DielectricObstacleLoss`
with a model that traces the direct path plus specular reflections off
building surfaces using the classical image method.

## The Image Method

The image method is a geometric technique for finding specular
reflection paths between a transmitter and receiver in the presence of
planar reflecting surfaces.  The key insight is that a specular
reflection off a planar surface is geometrically equivalent to a
straight-line path from a *mirror image* of the source.

### Single-bounce reflection

Given a transmitter at $\mathbf{T}$, a receiver at $\mathbf{R}$, and a
planar surface $S$:

1. Mirror $\mathbf{T}$ across $S$ to obtain the image source
   $\mathbf{T}'$.
2. The reflected ray path $\mathbf{T} \to P \to \mathbf{R}$ (where $P$
   is the reflection point on $S$) has the same geometry as the
   straight line $\mathbf{T}' \to \mathbf{R}$.
3. If the line $\mathbf{T}' \to \mathbf{R}$ intersects $S$ within the
   surface bounds, the reflection is valid and $P$ is the intersection
   point.

For an axis-aligned face with outward normal along the $x$-axis at
coordinate $x = x_0$, the image of $\mathbf{T} = (T_x, T_y, T_z)$ is:

$$
\mathbf{T}' = (2x_0 - T_x,\; T_y,\; T_z)
$$

### Two-bounce reflection

For a path $\mathbf{T} \to P_1 \to P_2 \to \mathbf{R}$ reflecting off
surface $A$ then surface $B$:

1. Mirror $\mathbf{T}$ across $A$ to get $\mathbf{T}_A$.
2. Mirror $\mathbf{T}_A$ across $B$ to get $\mathbf{T}_{AB}$.
3. If $\mathbf{T}_{AB} \to \mathbf{R}$ intersects $B$ at $P_2$, and
   $\mathbf{T}_A \to P_2$ intersects $A$ at $P_1$, the two-bounce
   path is valid.

This extends recursively to $N$ bounces, but computational cost grows
as $O(F^N)$ where $F$ is the number of building faces.

## Power Combination

Each valid propagation path contributes received power.  The module
computes the total received power as an **incoherent sum** of all path
contributions and returns the result as a loss factor relative to
free-space direct-path power.

### Direct path

The direct LOS path passes through any intervening buildings.  Each
building intersection incurs a penetration loss computed from the
material's conductivity and permittivity:

$$
L_{\text{penetration}} = e^{-2\alpha d}
$$

where $d$ is the material thickness traversed and $\alpha$ is the
attenuation constant:

$$
\alpha \approx \frac{60\pi\,\sigma}{\sqrt{\varepsilon_r}}
\quad [\text{Np/m}]
$$

This is the low-loss approximation for building materials.  For
concrete at 2.4 GHz ($\varepsilon_r = 5.31$, $\sigma = 0.0326$ S/m),
$\alpha \approx 2.67$ Np/m, giving roughly 23 dB/m penetration loss.

### Reflected paths

Each reflected path has power relative to the free-space direct path:

$$
P_{\text{reflected}} = \left(\frac{d_{\text{direct}}}{d_{\text{path}}}\right)^2
\cdot \prod_{i} \Gamma_i
$$

where $d_{\text{path}}$ is the total reflected path length (sum of all
legs), and $\Gamma_i$ is the Fresnel power reflection coefficient at the
$i$-th reflection point.

### Fresnel reflection coefficient

The reflection coefficient is the average of TE and TM polarisations
(unpolarised signal assumption):

$$
\Gamma = \frac{|r_s|^2 + |r_p|^2}{2}
$$

where:

$$
r_s = \frac{n_1 \cos\theta_i - n_2 \cos\theta_t}
           {n_1 \cos\theta_i + n_2 \cos\theta_t}, \qquad
r_p = \frac{n_2 \cos\theta_i - n_1 \cos\theta_t}
           {n_2 \cos\theta_i + n_1 \cos\theta_t}
$$

$n_1 = 1$ (air), $n_2 = \sqrt{\varepsilon_r}$ (building material),
$\theta_i$ is the angle of incidence (measured from the surface normal),
and $\theta_t$ is the refraction angle from Snell's law.

### Total loss factor

The module returns:

$$
L_{\text{total}} = \min\!\left(
  L_{\text{direct}} + \sum_k P_{\text{reflected},k},\;
  1.0
\right)
$$

The clamp to 1.0 prevents the incoherent sum from exceeding the
free-space power (no constructive interference modelling).

## Integration with INET

`ImageMethodObstacleLoss` extends INET's `TracingObstacleLossBase` and
implements the `IObstacleLoss` interface:

```cpp
double computeObstacleLoss(Hz frequency,
                           const Coord& transmissionPosition,
                           const Coord& receptionPosition) const;
```

The returned value is a multiplicative factor in $[0, 1]$ applied to
the free-space received power by INET's radio medium module
(`ScalarAnalogModelBase::computeReceptionPower`).

### Building face extraction

At initialisation, the module iterates all `IPhysicalObject` instances
in the `PhysicalEnvironment`, probes each shape along the three
coordinate axes to determine its half-extents, and creates six
axis-aligned `BuildingFace` structs per cuboid (in world coordinates).
This pre-extraction avoids repeated shape queries during simulation.

### NED configuration

```ini
# Use image method with 1-bounce reflections
*.radioMedium.obstacleLoss.typename = "ImageMethodObstacleLoss"
*.radioMedium.obstacleLoss.maxBounces = 1

# Material properties (concrete defaults)
*.radioMedium.obstacleLoss.buildingPermittivity = 5.31
*.radioMedium.obstacleLoss.buildingConductivity = 0.0326
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `maxBounces` | 0 | Max reflection bounces (0 = direct only, 1 = single, 2 = double) |
| `buildingPermittivity` | 5.31 | Relative permittivity $\varepsilon_r$ (concrete at 2.4 GHz) |
| `buildingConductivity` | 0.0326 | Conductivity $\sigma$ in S/m (concrete at 2.4 GHz) |

### Dataset generation

The `generate_scenario.py` and `generate_dataset.sh` scripts accept
`--obstacle-loss` and `--max-bounces` flags:

```bash
./datagen/generate_dataset.sh \
    --obstacle-loss ImageMethodObstacleLoss \
    --max-bounces 1 \
    --num-buildings 20 \
    --scenario-variants 10
```

## Computational Complexity

| Bounces | Complexity per TX–RX pair | Typical faces (20 buildings) |
|---------|--------------------------|------------------------------|
| 0 (direct only) | $O(B)$ | 20 objects |
| 1 (single bounce) | $O(F \cdot B)$ | 120 faces × 20 objects |
| 2 (double bounce) | $O(F^2 \cdot B)$ | 14400 face pairs × 20 objects |

$B$ is the number of building objects (for obstruction checks on each
path leg) and $F = 6B$ is the number of faces.  The obstruction check
for each leg iterates all objects, so the LOS-blocked test is $O(B)$.

For 20 buildings, single-bounce adds ~2400 obstruction checks per
TX–RX pair.  Double-bounce adds ~288,000.  This is acceptable for
small urban environments but may require spatial acceleration (e.g.
BVH or grid-based culling) for larger scenes.

## Inspirations

The implementation draws on two primary references:

**MATLAB Communications Toolbox — `rfprop.RayTracing`.**  MATLAB's
raytracing model offers both the Shooting and Bouncing Rays (SBR)
method and the image method.  The image method variant supports up to
2 reflections, matching our implementation.  Our approach follows the
same geometric construction (mirror images across reflecting surfaces)
and uses Fresnel equations for reflection loss.  MATLAB additionally
supports edge diffraction via the Uniform Theory of Diffraction, which
we do not implement (see Limitations).

**Kürner & Cichon, "A Tool for Raytracing Based Radio Channel
Simulation" (refs/).** This work describes a comprehensive
deterministic radio channel model using image-based raytracing with
specular reflections, diffuse scattering, and diffraction.  Our
implementation follows their approach of pre-extracting planar faces
from the building geometry and using mirror images to enumerate
reflection paths.  We use a simplified subset: axis-aligned cuboids
only, specular reflections only, and a single material class per
simulation (rather than per-surface material assignment).

## Limitations

### Axis-aligned buildings only

Building faces are extracted by probing shapes along the three
coordinate axes.  This works for the axis-aligned cuboids produced by
our `generate_buildings.py` tool but does not handle rotated buildings
or non-rectangular geometry (L-shapes, cylinders, etc.).

### No diffraction

The model does not compute diffracted rays around building edges.
Diffraction is the dominant propagation mechanism in deep shadow
regions (e.g. around corners), and its absence means the model
underestimates received power in non-line-of-sight scenarios where no
reflected path exists.  MATLAB's image method has the same limitation;
their SBR method adds diffraction support.

### No diffuse scattering

All reflections are specular (mirror-like).  Real building surfaces
have roughness that scatters energy in non-specular directions.  This
is most significant at higher frequencies (millimetre wave) and less
important at 2.4 GHz where surface roughness is small relative to the
wavelength.

### No ground reflection

The ground plane is not modelled as a reflecting surface.  In UAV
scenarios where both transmitter and receiver are tens of metres above
the ground, the ground reflection typically has a long path length and
a near-grazing incidence angle, making its contribution small relative
to building reflections.  Adding the ground as a single additional
reflecting plane is straightforward if needed.

### Uniform building material

All buildings share the same permittivity and conductivity, configured
once at the simulation level.  Real urban environments have varied
materials (concrete, glass, metal cladding) with different reflection
and penetration characteristics.  Per-building material assignment
would require extending the building generator to emit material
metadata alongside the geometry.

### Incoherent power summation

Path powers are summed incoherently (no phase information).  This
means the model cannot reproduce constructive or destructive
interference fading patterns.  In practice, the phase relationship
between paths changes rapidly with small position changes, so
incoherent summation gives the correct *average* received power.
The model does not produce fast fading; it produces a smooth spatial
power variation driven by path geometry.

### No frequency dependence in reflection

The reflection coefficient uses the real part of the refractive index
only ($n_2 = \sqrt{\varepsilon_r}$).  The imaginary component from
conductivity ($n_2 = \sqrt{\varepsilon_r - j\sigma/\omega\varepsilon_0}$)
is neglected.  This is a reasonable approximation for low-conductivity
building materials at 2.4 GHz but would underestimate reflection loss
for highly conductive surfaces (metal) or at lower frequencies.

### Computational cost at high bounce counts

Double-bounce is $O(F^2)$ per TX–RX pair.  With 20 buildings (120
faces), this is manageable.  Extending to 3+ bounces without spatial
acceleration structures would be prohibitively expensive for real-time
simulation with many hosts.
