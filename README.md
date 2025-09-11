# Drone Remote ID Network Simulator
This repository contains an [OMNeT++](https://omnetpp.org/) project for discrete event simulation of drone [Remote ID](https://www.ecfr.gov/current/title-14/part-89) networks.
The project makes use of [INET Framework](https://inet.omnetpp.org/) for realistic radio propagation, interference, and MAC-layer dynamics.

## Getting Started
First, install the following dependencies:
- [OMNeT++](https://omnetpp.org/download/)
- [INET Framework](https://inet.omnetpp.org/Installation.html)

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
9. Check that things are working by clicking the play button to "Run basic_uav"
10. In the OMNeT++ Qtenv window that pops up, select the `RandomMobility` config in the "Set Up Inifile Configuration" dialog and click OK
11. The visualization panel should show some UAVs and the simulation should be runnable via the toolbar buttons
