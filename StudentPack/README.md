# CENG 336 THE3 — EV Cabinet Student Pack

This pack contains the Python site supervisor and supporting files for
the THE3 EV cabinet assignment.

## Files

| Path | Purpose |
|---|---|
| `evCabinetSimulator.py` | Python supervisor; plays a scenario, displays the cabinet's reports. |
| `the3_template.c` | Optional C starter with byte queues and EUSART ISR structure. |
| `sample_scenario.json` | Canonical 7-second scenario from the assignment text. |
| `pragmas.h` | XC8 configuration pragmas for the PIC18F8722 at 40 MHz. |

## Running the simulator

    pip install pyserial pygame

The simulator uses `/dev/ttyUSB0` and 115200 baud by default. If your
board appears under another serial device name, add `--port DEVICE` to
the command.

Canonical scenario:

    python evCabinetSimulator.py sample_scenario.json

Manual probing through the UI:

    python evCabinetSimulator.py

Different serial device:

    python evCabinetSimulator.py --port /dev/ttyACM0 sample_scenario.json

Text trace only, without the pygame UI:

    python evCabinetSimulator.py --log-only sample_scenario.json
