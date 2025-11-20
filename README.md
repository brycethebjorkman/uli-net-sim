# Drone Remote ID Network Simulator
This repository contains an [OMNeT++](https://omnetpp.org/) project for discrete event simulation of drone [Remote ID](https://www.ecfr.gov/current/title-14/part-89) networks.
The project makes use of [INET Framework](https://inet.omnetpp.org/) for realistic radio propagation, interference, and MAC-layer dynamics.

## Getting Started
First, install the following dependencies:
- [OMNeT++](https://omnetpp.org/download/)
    - note: follow the instructions to build from source with OSG 3D graphics support, do not use the opp_env installer
- [INET Framework](https://inet.omnetpp.org/Installation.html)
    - note: do not use the opp_env installer, go through the OMNeT++ IDE
- [eigen library](https://gitlab.com/libeigen/eigen/-/releases)
    - download version 5.0.0 and place in OMNeT++ workspace alongside INET Framework

Your OMNeT++ workspace should now contain these directories:
- eigen-5.0.0
- inet4.5

Next, clone this repository and import the contained project into the OMNeT++ IDE:
1. Open the OMNeT++ IDE and choose a workspace directory
    - The default is fine, do not use the directory of this repository as a workspace
2. Open the Import dialog
    - File > Import or right-click in the Project Explorer view
3. Select the "Existing Projects into Workspace" import wizard
3. Select the directory of this repository as the root directory
5. The wizard should indicate that it found just a `uav-rid` project, which should be selected for import
    - Leave all other options unselected
6. After clicking "Finish", a `uav-rid` folder should appear in the Project Explorer view
7. Click on the `uav-rid` folder and navigate to its Properties dialog
    - Project > Properties or right-click it in Project Explorer and select Properties
8. Under "Project References" ensure there is a reference to INET such as `inet4.5`
9. Click into the inet project Properties > OMNeT++ > Project Features and enable `Visualization OSG (3D)`
10. Check that things are working by clicking the play button to "Run basic_uav"
11. In the OMNeT++ Qtenv window that pops up, select the `RandomMobility` config in the "Set Up Inifile Configuration" dialog and click OK
12. The visualization panel should show some UAVs and the simulation should be runnable via the toolbar buttons

## Project Structure
Source code for the project is split between:
- [simulations](./simulations) contains subdirectories defining different simulation scenarios consisting of:
    - Network Description (`.ned`) files which define the hierarchical structure of a simulation
    - runtime configuration (`.ini`) files which select the network to run and specify parameters, properties, and scenario variations
    - analysis configuration (`.anf`) files which define how simulation results are processed and visualized
- [src](./src) contains Network Description, C++, and Message Description (`.msg`) code defining custom module structures, behaviors, and messages  
