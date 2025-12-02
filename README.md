Automated Nanomaterial Synthesis Platform ("Lab-as-Code")

A Python-based infrastructure for the autonomous, closed-loop synthesis of nanomaterials (e.g., Ag2S Quantum Dots). This project replaces manual laboratory workflows with a modular, object-oriented codebase that orchestrates microfluidics, spectroscopy, and real-time data analysis.

🧪 Project Overview

The Problem: Vendor-provided software for lab hardware (pumps, spectrometers) is often fragmented, Windows-centric, and incapable of complex, event-driven logic.

The Solution: A unified Python abstraction layer that:

Wraps Low-Level C-DLLs: Converts raw vendor drivers (Elveflow, Ocean Optics) into high-level Python objects.

Manages State: Uses Context Managers (with statements) to ensure hardware safety (e.g., venting pressure on error).

Processes Data On-the-Fly: Analyzes spectral data in real-time to trigger hardware decisions (Closed-Loop).

📂 Repository Structure

├── Hardware_Drivers/       # Low-level hardware abstraction
│   ├── Elveflow_Core.py    # Base class wrapping C-DLLs with ctypes
│   ├── PressureController.py # OB1 Controller logic
│   ├── ValveController.py    # MUX Wire logic
│   └── StirrerController.py  # Binary protocol for hotplates
│
├── Experiment_Control/     # Main Application Logic
│   ├── FlowControl.py      # High-level liquid handling logic (Injection, Mixing)
│   └── run_experiment.py   # Main entry point for executing reaction plans
│
├── Analysis/               # Data Pipeline
│   ├── data_analysis.py    # Library for spectral smoothing (Savitzky-Golay), FWHM calc
│   └── process_data.py     # Batch processing script
│
└── requirements.txt        # Dependencies


🚀 Key Features

1. Hardware Abstraction (Elveflow & Ocean Optics)

Instead of dealing with raw pointers and memory management in every script, the hardware is abstracted into safe classes:

# Instead of 20 lines of C-types code:
with PressureController(serial="01234") as ob1:
    ob1.set_pressure(channel=1, mbar=200)
    ob1.add_flow_sensor(channel=1, type=5)


2. Closed-Loop Automation

The system runs reactions autonomously based on a generated plan. It monitors spectral emission in real-time and can terminate reactions based on stability thresholds.

3. Automated Data Pipeline

Raw data is automatically:

Cleaned: Aligned to theoretical time axes.

Smoothed: Using Savitzky-Golay filters.

Analyzed: Peak position and FWHM (in eV) are extracted using Jacobian transformations.

🛠️ Installation & Usage

Install Dependencies:

pip install -r requirements.txt


Run an Experiment:

python Experiment_Control/run_experiment.py


Process Data:

python Analysis/process_data.py --data_dir "C:/data/2025-12-01"


⚠️ Disclaimer

This code controls physical hardware involving pressurized liquids and chemicals. It includes safety mechanisms (emergency stops, pressure venting), but should only be operated by trained personnel.