#!/usr/bin/env python3
"""
generate_bom.py
===============
Generates a synthetic automotive Bill-of-Materials as an RDF Turtle file
(apex_bom.ttl) for the fictional "Apex Meridian" car range.

Design decisions
----------------
* Quantity is modelled via a reified bom:PartLink node (Assembly → PartLink →
  Part) rather than a plain datatype property on bom:Part.  This lets the same
  part URI appear in multiple assemblies with different quantities — essential
  for modelling the ≥20 % shared-parts requirement.
* All data is synthetic and fictional; no real OEM part numbers are used.
* The script is deterministic for a fixed SEED so results are reproducible.

Usage
-----
    python generate_bom.py              # writes apex_bom.ttl in the CWD
    python generate_bom.py --out /path  # custom output path
    python generate_bom.py --seed 99    # different random seed
"""

import argparse
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────

SEED = 42
BASE_NS = "http://ibom.ai/data/bom#"
ONT_NS  = "http://ibom.ai/ontology/bom#"
XSD_NS  = "http://www.w3.org/2001/XMLSchema#"
RDF_NS  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

VARIANTS = {
    "SEDAN":  "Apex Meridian Sedan",
    "SUV":    "Apex Meridian SUV",
    "COUPE":  "Apex Meridian Coupe",
    "HATCH":  "Apex Meridian Hatchback",
    "ESTATE": "Apex Meridian Estate",
}

# Each system entry: (system_key, display_name, assemblies_spec)
# assemblies_spec maps assembly_key → (display_name, base_part_count_range)
# Part counts may be overridden per variant below.
SYSTEMS = {
    "engine": {
        "name": "Engine",
        "assemblies": {
            "cyl_block":    ("Cylinder Block Assembly",   (14, 18)),
            "cyl_head":     ("Cylinder Head Assembly",    (12, 16)),
            "fuel_delivery":("Fuel Delivery Assembly",    (10, 14)),
            "lubrication":  ("Lubrication Assembly",      (8,  12)),
            "cooling":      ("Cooling Assembly",          (10, 14)),
        },
    },
    "transmission": {
        "name": "Transmission",
        "assemblies": {
            "gearbox":      ("Gearbox Assembly",          (12, 16)),
            "driveshaft":   ("Driveshaft Assembly",       (8,  12)),
            "differential": ("Differential Assembly",     (8,  12)),
            "clutch":       ("Clutch Assembly",           (6,  10)),
        },
    },
    "chassis": {
        "name": "Chassis & Frame",
        "assemblies": {
            "front_subframe":("Front Subframe Assembly",  (10, 14)),
            "rear_subframe": ("Rear Subframe Assembly",   (10, 14)),
            "cross_members": ("Cross-Members Assembly",   (8,  12)),
            "tow_bar":       ("Tow Bar Assembly",         (4,   8)),
        },
    },
    "suspension": {
        "name": "Suspension & Steering",
        "assemblies": {
            "front_strut":  ("Front Strut Assembly",      (12, 18)),
            "rear_multilink":("Rear Multi-Link Assembly", (12, 18)),
            "steer_col":    ("Steering Column Assembly",  (8,  12)),
            "power_steer":  ("Power Steering Assembly",   (8,  12)),
        },
    },
    "brakes": {
        "name": "Brakes",
        "assemblies": {
            "front_caliper":("Front Caliper Assembly",    (6,  10)),
            "rear_caliper": ("Rear Caliper Assembly",     (6,  10)),
            "abs_module":   ("ABS Module Assembly",       (6,   8)),
            "brake_lines":  ("Brake Lines Assembly",      (5,   9)),
        },
    },
    "body": {
        "name": "Body & Exterior",
        "assemblies": {
            "door_panels":  ("Door Panel Assembly",       (12, 18)),
            "bonnet":       ("Bonnet Assembly",           (6,  10)),
            "boot_tailgate":("Boot / Tailgate Assembly",  (8,  14)),
            "bumpers":      ("Bumpers Assembly",          (8,  12)),
            "glass":        ("Glass Assembly",            (6,  10)),
        },
    },
    "electrical": {
        "name": "Electrical & Electronics",
        "assemblies": {
            "wiring":       ("Wiring Harness Assembly",   (18, 24)),
            "battery":      ("Battery Assembly",          (6,   8)),
            "ecu":          ("ECU Assembly",              (8,  12)),
            "lighting":     ("Lighting Assembly",         (10, 16)),
            "sensors":      ("Sensors Assembly",          (12, 18)),
        },
    },
}

# Per-variant part-count multipliers (relative to base spec).
# SUV and ESTATE are larger/heavier; COUPE is lighter.
VARIANT_MULTIPLIER = {
    "SEDAN":  1.0,
    "SUV":    1.25,
    "COUPE":  0.85,
    "HATCH":  0.90,
    "ESTATE": 1.10,
}

# SUV gets an extra assembly in suspension & chassis; ESTATE gets tow-bar extras.
VARIANT_EXTRA_ASSEMBLIES: dict[str, dict[str, list[tuple[str, str, tuple[int,int]]]]] = {
    "SUV": {
        "suspension": [("awd_transfer", "AWD Transfer Case Assembly", (8, 12))],
        "chassis":    [("skid_plate",   "Skid Plate Assembly",        (4,  6))],
    },
    "COUPE": {
        "engine":     [("sport_exhaust","Sport Exhaust Assembly",     (6, 10))],
    },
    "ESTATE": {
        "chassis":    [("roof_rails",   "Roof Rail Assembly",         (4,  6))],
    },
}

# Cost and weight bands per system (realistic plausibility)
SYSTEM_COST_BAND: dict[str, tuple[float, float]] = {
    "engine":       (5.00, 2500.0),
    "transmission": (8.00, 1800.0),
    "chassis":      (1.00,  600.0),
    "suspension":   (2.00,  900.0),
    "brakes":       (1.50,  750.0),
    "body":         (0.50,  400.0),
    "electrical":   (0.05,  800.0),
}
SYSTEM_WEIGHT_BAND: dict[str, tuple[float, float]] = {
    "engine":       (0.05, 45.0),
    "transmission": (0.10, 30.0),
    "chassis":      (0.20, 40.0),
    "suspension":   (0.05, 25.0),
    "brakes":       (0.05, 12.0),
    "body":         (0.10, 20.0),
    "electrical":   (0.001, 5.0),
}

# ─────────────────────────────────────────────────────────────
#  Part name vocabulary per system
# ─────────────────────────────────────────────────────────────

PART_VOCAB: dict[str, list[str]] = {
    "engine": [
        "Crankshaft", "Camshaft Intake", "Camshaft Exhaust", "Piston", "Piston Ring Set",
        "Piston Pin", "Connecting Rod", "Connecting Rod Bolt", "Cylinder Liner",
        "Main Bearing Upper", "Main Bearing Lower", "Big End Bearing", "Thrust Washer",
        "Cylinder Head Bolt M10", "Cylinder Head Bolt M12", "Head Gasket MLS",
        "Head Gasket Composite", "Valve Intake 31mm", "Valve Intake 33mm",
        "Valve Exhaust 27mm", "Valve Exhaust 29mm", "Valve Spring Inner",
        "Valve Spring Outer", "Valve Retainer", "Valve Cotters",
        "Valve Stem Seal", "Valve Guide", "Valve Seat Insert",
        "Camshaft Sprocket Intake", "Camshaft Sprocket Exhaust",
        "Crankshaft Sprocket", "Timing Chain Primary", "Timing Chain Secondary",
        "Timing Chain Guide Primary", "Timing Chain Guide Secondary",
        "Timing Chain Tensioner Primary", "Timing Chain Tensioner Secondary",
        "VVT Solenoid Intake", "VVT Solenoid Exhaust", "VVT Actuator Intake",
        "Oil Pump", "Oil Pump Drive Chain", "Oil Pan Upper", "Oil Pan Lower",
        "Oil Filter Housing", "Oil Filter Cartridge", "Oil Cooler Core",
        "Oil Pressure Sensor", "Oil Level Sensor", "Oil Temperature Sensor",
        "Coolant Pump", "Coolant Pump Belt", "Coolant Thermostat",
        "Coolant Thermostat Housing", "Coolant Expansion Tank",
        "Radiator Hose Upper", "Radiator Hose Lower", "Radiator Hose Bypass",
        "Coolant Temperature Sensor NTC", "Heater Matrix Core",
        "Fuel Injector 450cc", "Fuel Injector 550cc", "Fuel Rail Aluminium",
        "Fuel Pressure Regulator", "Fuel Pressure Sensor",
        "Intake Manifold Upper", "Intake Manifold Lower", "Intake Plenum",
        "Exhaust Manifold Cast Iron", "Exhaust Manifold Stainless",
        "Exhaust Manifold Gasket", "Turbocharger Cartridge Small",
        "Turbocharger Cartridge Large", "Turbo Oil Feed Pipe",
        "Turbo Oil Return Pipe", "Wastegate Actuator", "Blow-Off Valve",
        "Intercooler Core Bar-and-Plate", "Intercooler Core Tube-and-Fin",
        "Charge Air Pipe Silicone", "Throttle Body 60mm", "Throttle Body 70mm",
        "Throttle Body Gasket", "Mass Airflow Sensor Hot-Wire",
        "Lambda Sensor Pre-Cat", "Lambda Sensor Post-Cat",
        "Crankshaft Position Sensor", "Camshaft Position Sensor Intake",
        "Camshaft Position Sensor Exhaust", "Knock Sensor",
        "Manifold Absolute Pressure Sensor", "Coolant Temp Sensor ECU",
        "Spark Plug Iridium", "Spark Plug Platinum", "Ignition Coil COP",
        "Flywheel Dual-Mass", "Flywheel Single-Mass", "Starter Motor 1.2kW",
        "Starter Motor 1.8kW", "Alternator 120A", "Alternator 180A",
        "Serpentine Belt 6PK", "Belt Tensioner Pulley", "Belt Idler Pulley",
        "Harmonic Balancer", "Engine Mount Rubber Bush Front",
        "Engine Mount Rubber Bush Rear", "Engine Mount Hydraulic",
        "Oil Filler Cap", "PCV Valve", "PCV Hose", "EGR Valve",
        "EGR Cooler", "EGR Pipe", "Charge Air Pipe Aluminium",
        "Dipstick Tube", "Breather Hose", "Vacuum Pump", "Vacuum Reservoir",
    ],
    "transmission": [
        "Input Shaft 6-spd", "Input Shaft 8-spd", "Output Shaft 6-spd",
        "Output Shaft 8-spd", "Layshaft Primary", "Layshaft Secondary",
        "Synchroniser Ring 1-2", "Synchroniser Ring 3-4", "Synchroniser Ring 5-6",
        "Synchroniser Hub 1-2", "Synchroniser Hub 3-4",
        "Gear 1st 3.54", "Gear 1st 3.77", "Gear 2nd 2.06", "Gear 2nd 2.21",
        "Gear 3rd 1.40", "Gear 3rd 1.52", "Gear 4th 1.00", "Gear 5th 0.81",
        "Gear 6th 0.64", "Gear 6th 0.69", "Reverse Gear", "Reverse Idler Gear",
        "Differential Crown Wheel", "Differential Pinion",
        "Differential Spider Gear", "Differential Side Gear",
        "Differential Case", "Differential Bearing",
        "Clutch Disc 228mm", "Clutch Disc 240mm", "Clutch Pressure Plate 228mm",
        "Clutch Pressure Plate 240mm", "Clutch Release Bearing",
        "Clutch Fork", "Clutch Slave Cylinder", "Clutch Master Cylinder",
        "Clutch Hydraulic Line", "Dual-Mass Flywheel Spring Set",
        "Gearbox Casing Aluminium", "Gearbox End Cover",
        "Gearbox Seal Rear", "Gearbox Seal Input", "Gearbox Vent Plug",
        "Gearbox Mounting Bracket", "Gearbox Mounting Bush",
        "Driveshaft Inner CV Joint 100mm", "Driveshaft Inner CV Joint 108mm",
        "Driveshaft Outer CV Joint 82mm", "Driveshaft Outer CV Joint 90mm",
        "CV Boot Inner", "CV Boot Outer", "Driveshaft Circlip 42mm",
        "Driveshaft Intermediate Shaft", "Intermediate Shaft Bearing",
        "Prop Shaft Coupling Rubber", "Prop Shaft Centre Bearing",
        "Transfer Case Chain", "Transfer Case Sprocket Front",
        "Transfer Case Sprocket Rear", "Transfer Case Pump",
        "Gear Selector Fork 1-2", "Gear Selector Fork 3-4",
        "Shift Rail 1-2", "Shift Rail 3-4", "Detent Ball", "Detent Spring",
        "Gearbox Oil Filter", "Gearbox Breather Valve", "Shift Cable",
        "Torque Converter 240mm", "ATF Pump", "Valve Body Assembly",
        "Planetary Gear Set Front", "Planetary Gear Set Rear",
        "Multi-Disc Clutch Pack A", "Multi-Disc Clutch Pack B",
        "Solenoid Pack ATF", "ATF Cooler Tube",
    ],
    "chassis": [
        "Front Subframe Beam Pressed Steel", "Front Subframe Beam Aluminium",
        "Front Subframe Bracket Left", "Front Subframe Bracket Right",
        "Front Subframe Bushing M12", "Rear Subframe Beam Pressed Steel",
        "Rear Subframe Beam Aluminium", "Rear Subframe Mounting Bush 45mm",
        "Rear Subframe Mounting Bush 60mm", "Rear Subframe Bolt M14",
        "Cross-Member Front Upper", "Cross-Member Front Lower",
        "Cross-Member Rear", "Cross-Member Centre Tunnel",
        "Longitudinal Rail Left Inner", "Longitudinal Rail Left Outer",
        "Longitudinal Rail Right Inner", "Longitudinal Rail Right Outer",
        "Body Mount Rubber Front", "Body Mount Rubber Rear",
        "Body Mount Washer", "Radiator Support Panel Upper",
        "Radiator Support Panel Lower", "Engine Cradle Bolt M12",
        "Engine Cradle Nut M12", "Jacking Point Reinforcement Left",
        "Jacking Point Reinforcement Right", "Tow Hook Front",
        "Tow Hook Rear", "Tow Hook Thread Insert M18",
        "Tow Bar Arm Pressed", "Tow Bar Ball 50mm",
        "Tow Bar Electrical Connector 7-pin", "Tow Bar Electrical Connector 13-pin",
        "Tow Bar Safety Chain D-Ring", "Tow Bar Mounting Bracket",
        "Tow Bar Mounting Bolt M12", "Underbody Shield Front Polypropylene",
        "Underbody Shield Rear Polypropylene", "Undertray Side Left",
        "Undertray Side Right", "Roof Rail Bracket Aluminium",
        "Roof Rail Extrusion Left", "Roof Rail Extrusion Right",
        "Roof Rail End Cap", "Skid Plate Steel 3mm", "Skid Plate Skid Bolt M8",
        "Side Sill Reinforcement Left", "Side Sill Reinforcement Right",
        "A-Pillar Reinforcement Left", "A-Pillar Reinforcement Right",
        "B-Pillar Reinforcement Left", "B-Pillar Reinforcement Right",
        "C-Pillar Reinforcement Left", "C-Pillar Reinforcement Right",
        "D-Pillar Reinforcement Left", "D-Pillar Reinforcement Right",
        "Firewall Reinforcement Panel", "Floor Pan Front",
        "Floor Pan Rear", "Boot Floor Panel", "Spare Wheel Well",
        "Chassis Weld Nut M8", "Chassis Weld Nut M10",
    ],
    "suspension": [
        "Front Coil Spring 320N/mm", "Front Coil Spring 360N/mm",
        "Front Coil Spring 400N/mm", "Front Shock Absorber Monotube",
        "Front Shock Absorber Twin-Tube", "Front Shock Absorber Sport",
        "Front Strut Bearing Thrust", "Front Strut Top Mount Rubber",
        "Front Strut Top Mount Hydraulic", "Front Strut Dust Boot",
        "Front Strut Bump Stop", "Front Anti-Roll Bar 21mm",
        "Front Anti-Roll Bar 24mm", "Front ARB Drop Link Left",
        "Front ARB Drop Link Right", "Front ARB Bush 21mm",
        "Front ARB Bush 24mm", "Front Lower Arm Pressed Steel",
        "Front Lower Arm Aluminium", "Front Lower Arm Ball Joint",
        "Front Lower Arm Bushing Inner", "Front Lower Arm Bushing Outer",
        "Front Upper Arm Aluminium", "Front Upper Arm Bush",
        "Front Wheel Bearing Unit 72mm", "Front Wheel Bearing Unit 80mm",
        "Front Hub Carrier Cast Iron", "Front Hub Carrier Aluminium",
        "Front Knuckle Forged", "Front Knuckle Bracket",
        "Rear Coil Spring 200N/mm", "Rear Coil Spring 240N/mm",
        "Rear Shock Absorber Monotube", "Rear Shock Absorber Twin-Tube",
        "Rear Shock Absorber Self-Levelling", "Rear Shock Dust Boot",
        "Rear Shock Bump Stop", "Rear Trailing Arm Left",
        "Rear Trailing Arm Right", "Rear Trailing Arm Bushing",
        "Rear Upper Control Arm Left", "Rear Upper Control Arm Right",
        "Rear Upper Control Arm Bushing", "Rear Lower Control Arm Left",
        "Rear Lower Control Arm Right", "Rear Lower Control Arm Bushing",
        "Rear Toe Link Left", "Rear Toe Link Right", "Rear Toe Link Bushing",
        "Rear Anti-Roll Bar 18mm", "Rear Anti-Roll Bar 21mm",
        "Rear ARB Drop Link Left", "Rear ARB Drop Link Right",
        "Rear ARB Bush 18mm", "Rear ARB Bush 21mm",
        "Rear Knuckle Forged", "Rear Hub Carrier Cast Iron",
        "Rear Wheel Bearing Unit 72mm", "Rear Wheel Bearing Unit 80mm",
        "Steering Rack Housing Aluminium", "Steering Rack Pinion",
        "Steering Rack Tie Rod Inner Left", "Steering Rack Tie Rod Inner Right",
        "Steering Rack Gaiter Left", "Steering Rack Gaiter Right",
        "Tie Rod End Left", "Tie Rod End Right",
        "Steering Column Shaft Lower", "Steering Column Shaft Upper",
        "Steering Column Universal Joint Lower", "Steering Column Universal Joint Upper",
        "Steering Column Bearing", "Steering Column Shroud",
        "Power Steering Pump Hydraulic", "Power Steering Pump EPS Motor",
        "Power Steering Reservoir", "PS High-Pressure Hose",
        "PS Return Hose", "PS Fluid Cooler",
        "AWD Coupling Haldex Gen4", "AWD Transfer Case",
        "Propshaft Centre Support Bearing", "Propshaft Front Section",
        "Propshaft Rear Section", "Propshaft Flex Coupling",
    ],
    "brakes": [
        "Front Brake Disc 300mm Vented", "Front Brake Disc 320mm Vented",
        "Front Brake Disc 340mm Drilled", "Front Brake Pad Set Sport",
        "Front Brake Pad Set OE", "Front Caliper Body Single-Piston",
        "Front Caliper Body Twin-Piston", "Front Caliper Piston 54mm",
        "Front Caliper Piston 60mm", "Front Caliper Seal Kit",
        "Front Caliper Bolt M12", "Front Caliper Guide Pin",
        "Front Caliper Slide Pin Bush", "Front Brake Disc Bolt M8",
        "Rear Brake Disc 280mm Solid", "Rear Brake Disc 300mm Vented",
        "Rear Brake Pad Set OE", "Rear Brake Pad Set Low-Dust",
        "Rear Caliper Body Single-Piston", "Rear Caliper Piston 38mm",
        "Rear Caliper Piston 44mm", "Rear Caliper Adjuster Mechanism",
        "Rear Caliper Seal Kit", "Rear Caliper Bolt M10",
        "Handbrake Cable Left", "Handbrake Cable Right",
        "Handbrake Lever Assembly", "Handbrake Mechanism",
        "Electronic Parking Brake Motor Left", "Electronic Parking Brake Motor Right",
        "Brake Master Cylinder 23mm", "Brake Master Cylinder 25mm",
        "Brake Servo Tandem 8-inch", "Brake Servo Tandem 9-inch",
        "Brake Servo Vacuum Hose", "Brake Fluid Reservoir",
        "Brake Fluid Level Sensor", "ABS Pump / HCU Assembly",
        "ABS ECU Module", "Wheel Speed Sensor Front Left",
        "Wheel Speed Sensor Front Right", "Wheel Speed Sensor Rear Left",
        "Wheel Speed Sensor Rear Right", "ABS Reluctor Ring Front",
        "ABS Reluctor Ring Rear", "Brake Line Hard Pipe Front Left",
        "Brake Line Hard Pipe Front Right", "Brake Line Hard Pipe Rear Left",
        "Brake Line Hard Pipe Rear Right", "Brake Line Hard Pipe Crossover",
        "Brake Flexi Hose Front Left", "Brake Flexi Hose Front Right",
        "Brake Flexi Hose Rear Left", "Brake Flexi Hose Rear Right",
        "Brake Proportioning Valve", "Brake Pad Wear Sensor Front",
        "Brake Pad Wear Sensor Rear", "Brake Caliper Paint Kit",
    ],
    "body": [
        "Front Door Inner Panel Left", "Front Door Inner Panel Right",
        "Front Door Outer Panel Left", "Front Door Outer Panel Right",
        "Front Door Hinge Upper Left", "Front Door Hinge Upper Right",
        "Front Door Hinge Lower Left", "Front Door Hinge Lower Right",
        "Front Door Check Strap Left", "Front Door Check Strap Right",
        "Front Door Latch Left", "Front Door Latch Right",
        "Rear Door Inner Panel Left", "Rear Door Inner Panel Right",
        "Rear Door Outer Panel Left", "Rear Door Outer Panel Right",
        "Rear Door Hinge Upper Left", "Rear Door Hinge Upper Right",
        "Rear Door Hinge Lower Left", "Rear Door Hinge Lower Right",
        "Rear Door Latch Left", "Rear Door Latch Right",
        "Bonnet Outer Panel Steel", "Bonnet Outer Panel Aluminium",
        "Bonnet Inner Panel", "Bonnet Hinge Left", "Bonnet Hinge Right",
        "Bonnet Latch Primary", "Bonnet Latch Safety", "Bonnet Gas Strut Left",
        "Bonnet Gas Strut Right", "Bonnet Weatherstrip",
        "Boot Lid Outer Steel", "Boot Lid Outer Aluminium",
        "Boot Lid Inner Panel", "Boot Lid Hinge Left", "Boot Lid Hinge Right",
        "Boot Lid Lock Cylinder", "Boot Lid Gas Strut Left",
        "Boot Lid Gas Strut Right", "Boot Lid Weatherstrip",
        "Tailgate Outer Panel", "Tailgate Inner Panel",
        "Tailgate Hinge Left", "Tailgate Hinge Right",
        "Tailgate Spoiler", "Tailgate Wiper Motor",
        "Tailgate Gas Strut Left", "Tailgate Gas Strut Right",
        "Tailgate Lock Mechanism", "Tailgate Weatherstrip",
        "Front Bumper Beam Steel", "Front Bumper Beam Aluminium",
        "Front Bumper Cover Unpainted", "Front Bumper Foam Absorber",
        "Front Bumper Grille Upper", "Front Bumper Grille Lower",
        "Front Bumper Retainer Clip Set", "Front Bumper Bracket Left",
        "Front Bumper Bracket Right", "Front Bumper Tow Eye Cover",
        "Rear Bumper Beam Steel", "Rear Bumper Cover Unpainted",
        "Rear Bumper Foam Absorber", "Rear Bumper Retainer Clip Set",
        "Rear Bumper Bracket Left", "Rear Bumper Bracket Right",
        "Windscreen Glass Laminated", "Windscreen Bonding Adhesive",
        "Windscreen Moulding Upper", "Windscreen Moulding Side",
        "Rear Windscreen Glass Heated", "Rear Windscreen Moulding",
        "Front Quarter Glass Left", "Front Quarter Glass Right",
        "Rear Quarter Glass Left", "Rear Quarter Glass Right",
        "Sunroof Glass Laminated", "Sunroof Frame Aluminium",
        "Sunroof Mechanism Motor", "Sunroof Sunshade",
        "Wing Mirror Housing Left", "Wing Mirror Housing Right",
        "Wing Mirror Glass Heated Left", "Wing Mirror Glass Heated Right",
        "Wing Mirror Folding Motor Left", "Wing Mirror Folding Motor Right",
        "Door Seal Rubber Front Left", "Door Seal Rubber Front Right",
        "Door Seal Rubber Rear Left", "Door Seal Rubber Rear Right",
        "Bonnet Seal Rubber", "Boot Seal Rubber",
        "Drip Rail Moulding Left", "Drip Rail Moulding Right",
        "Roof Panel Steel", "Roof Bow Front", "Roof Bow Rear",
        "Wheel Arch Liner Front Left", "Wheel Arch Liner Front Right",
        "Wheel Arch Liner Rear Left", "Wheel Arch Liner Rear Right",
        "Side Step Left", "Side Step Right",
        "Running Board Left", "Running Board Right",
    ],
    "electrical": [
        "Main Wiring Harness Engine Bay", "Main Wiring Harness Cabin Front",
        "Main Wiring Harness Cabin Rear", "Main Wiring Harness Chassis",
        "Main Wiring Harness Door Front Left", "Main Wiring Harness Door Front Right",
        "Main Wiring Harness Door Rear Left", "Main Wiring Harness Door Rear Right",
        "Wiring Harness Roof", "Wiring Harness Boot",
        "Connector Block 20-pin", "Connector Block 40-pin",
        "Connector Block 80-pin", "Inline Connector 6-pin",
        "Inline Connector 12-pin", "Fuse Box Assembly Engine Bay",
        "Fuse Box Assembly Cabin", "Relay Module 8-way",
        "Relay Module 16-way", "Relay Starter",
        "12V Battery 70Ah EFB", "12V Battery 95Ah AGM",
        "12V Battery 110Ah AGM", "Battery Positive Lead 25mm2",
        "Battery Negative Lead 16mm2", "Battery Clamp Set",
        "Battery Tray Plastic", "Battery Hold-Down Bracket",
        "Body Control Module BCM", "Engine Control Unit ECU Bosch MG1",
        "Engine Control Unit ECU Continental SIM2K",
        "Transmission Control Module TCM", "All-Wheel-Drive Control Module",
        "Instrument Cluster Display TFT", "Instrument Cluster Display LCD",
        "Central Infotainment Head Unit 8-inch",
        "Central Infotainment Head Unit 10-inch",
        "Amplifier 4-channel", "Speaker Front Door Left",
        "Speaker Front Door Right", "Speaker Rear Door Left",
        "Speaker Rear Door Right", "Tweeter Front Left", "Tweeter Front Right",
        "Subwoofer Boot", "CANBUS Gateway Module",
        "Airbag Control Module ACM", "Airbag Driver 2-stage",
        "Airbag Passenger 2-stage", "Airbag Knee Driver",
        "Side Curtain Airbag Left", "Side Curtain Airbag Right",
        "Side Thorax Airbag Front Left", "Side Thorax Airbag Front Right",
        "Crash Sensor Front", "Crash Sensor Side Left", "Crash Sensor Side Right",
        "Seatbelt Pre-tensioner Front Left", "Seatbelt Pre-tensioner Front Right",
        "Seatbelt Pre-tensioner Rear Centre", "Seatbelt Load Limiter",
        "Front Headlamp Assembly LED Left", "Front Headlamp Assembly LED Right",
        "Front Headlamp Assembly Halogen Left", "Front Headlamp Assembly Halogen Right",
        "Daytime Running Light Strip Left", "Daytime Running Light Strip Right",
        "DRL Module Controller", "Headlamp Level Sensor Left",
        "Headlamp Level Sensor Right", "Headlamp Washer Nozzle Left",
        "Headlamp Washer Nozzle Right", "Rear Tail Lamp LED Left",
        "Rear Tail Lamp LED Right", "Rear Fog Lamp Left", "Rear Fog Lamp Right",
        "Fog Lamp Front Left", "Fog Lamp Front Right",
        "Reversing Lamp Bulb", "Reversing Lamp Housing",
        "Number Plate Light Left", "Number Plate Light Right",
        "Interior Dome Light", "Footwell Light Front", "Footwell Light Rear",
        "Reading Light Front", "Ambient Light Strip",
        "Horn Assembly Dual-Tone", "Horn Relay",
        "Rain Sensor Optical", "Light Sensor Ambient",
        "Parking Sensor Front 1", "Parking Sensor Front 2",
        "Parking Sensor Front 3", "Parking Sensor Rear 1",
        "Parking Sensor Rear 2", "Parking Sensor Rear 3",
        "Parking Sensor Rear 4", "Parking Sensor ECU",
        "Rear-View Camera 1080p", "Rear-View Camera Wide-Angle",
        "Front Camera ADAS", "Surround-View Camera Left",
        "Surround-View Camera Right", "Surround-View ECU",
        "Blind Spot Radar Left", "Blind Spot Radar Right",
        "Forward Collision Radar", "Adaptive Cruise Control Radar",
        "Lane Keep Assist Camera", "TPMS Sensor 315MHz",
        "TPMS Sensor 433MHz", "TPMS Receiver Module",
        "Cruise Control Stalk", "Cruise Control Module",
        "Electric Window Motor Front Left", "Electric Window Motor Front Right",
        "Electric Window Motor Rear Left", "Electric Window Motor Rear Right",
        "Electric Window Regulator Front Left", "Electric Window Regulator Front Right",
        "Electric Window Regulator Rear Left", "Electric Window Regulator Rear Right",
        "Central Locking Actuator Front Left", "Central Locking Actuator Front Right",
        "Central Locking Actuator Rear Left", "Central Locking Actuator Rear Right",
        "Central Locking Actuator Boot",
        "Remote Keyless Entry Module", "Transponder Antenna Loop",
        "USB Hub Module", "12V Socket Accessory",
        "Wireless Charging Pad", "Navigation Antenna GPS",
        "DAB Radio Antenna", "4G LTE Antenna",
    ],
}

# Variant-specific part name suffixes — appended to a base name to create
# a unique part URI while retaining the system key for cost/weight banding.
# Parts with a suffix are variant-specific (not shared across variants).
VARIANT_SPECIFIC_SUFFIX: dict[str, str] = {
    "SEDAN":  " [Sedan]",
    "SUV":    " [SUV]",
    "COUPE":  " [Coupe]",
    "HATCH":  " [Hatch]",
    "ESTATE": " [Estate]",
}

# Fraction of parts in each assembly that are variant-specific (rest are shared).
# This gives us both enough unique parts AND ≥20 % shared.
VARIANT_SPECIFIC_FRACTION = 0.35   # 35 % unique per variant, 65 % shared

# ─────────────────────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────────────────────

@dataclass
class Part:
    uri:          str
    name:         str
    number:       str
    unit_cost:    float
    unit_weight:  float

@dataclass
class PartLink:
    uri:      str
    part_uri: str
    quantity: int

@dataclass
class Assembly:
    uri:        str
    name:       str
    part_links: list[PartLink] = field(default_factory=list)

@dataclass
class System:
    uri:        str
    name:       str
    assemblies: list[Assembly] = field(default_factory=list)

@dataclass
class Vehicle:
    uri:     str
    code:    str
    name:    str
    systems: list[System] = field(default_factory=list)

# ─────────────────────────────────────────────────────────────
#  Generator
# ─────────────────────────────────────────────────────────────

class BomGenerator:
    def __init__(self, seed: int = SEED):
        self.rng = random.Random(seed)
        self.parts: dict[str, Part] = {}      # uri → Part
        self.vehicles: list[Vehicle] = []

        # Pool of named parts per system that can be reused across variants.
        # Maps (system_key, part_name) → Part  so the same part name always
        # maps to the same URI and therefore the same cost/weight.
        self._part_pool: dict[tuple[str, str], Part] = {}
        self._part_link_counter = 0

    # ── helpers ──────────────────────────────────────────────

    def _slug(self, text: str) -> str:
        """Convert a display name into a URI-safe slug."""
        return (text.lower()
                    .replace(" ", "_")
                    .replace("/", "_")
                    .replace("&", "and")
                    .replace("-", "_")
                    .replace(",", "")
                    .replace(".", "")
                    .replace("'", "")
                    .replace("(", "")
                    .replace(")", ""))

    def _make_part_number(self, system_key: str, part_name: str) -> str:
        prefix = {
            "engine":       "APX-ENG",
            "transmission": "APX-TRN",
            "chassis":      "APX-CHS",
            "suspension":   "APX-SUS",
            "brakes":       "APX-BRK",
            "body":         "APX-BDY",
            "electrical":   "APX-ELC",
        }.get(system_key, "APX-GEN")
        # Deterministic suffix from name
        numeric = abs(hash(part_name)) % 90000 + 10000
        return f"{prefix}-{numeric}"

    def _get_or_create_part(self, system_key: str, part_name: str) -> Part:
        """Return an existing part from the pool or create a new one."""
        key = (system_key, part_name)
        if key not in self._part_pool:
            uri  = f"{BASE_NS}part_{self._slug(part_name)}_{system_key}"
            num  = self._make_part_number(system_key, part_name)
            cmin, cmax = SYSTEM_COST_BAND[system_key]
            wmin, wmax = SYSTEM_WEIGHT_BAND[system_key]
            cost   = round(self.rng.uniform(cmin, cmax), 2)
            weight = round(self.rng.uniform(wmin, wmax), 4)
            part   = Part(uri=uri, name=part_name, number=num,
                          unit_cost=cost, unit_weight=weight)
            self._part_pool[key] = part
            self.parts[uri] = part
        return self._part_pool[key]

    def _next_part_link_uri(self, assembly_uri: str, idx: int) -> str:
        return f"{assembly_uri}_link_{idx:04d}"

    def _build_assembly(self, variant_code: str, system_key: str,
                         assembly_key: str, display_name: str,
                         count_range: tuple[int, int],
                         multiplier: float) -> Assembly:
        """Build an Assembly with a mix of shared and variant-specific parts.

        shared parts     → use base part name; URI is the same across variants.
        variant-specific → append a variant suffix to the name; distinct URI.
        """
        vocab = PART_VOCAB[system_key]
        lo, hi = count_range
        total_count = max(2, int(self.rng.randint(lo, hi) * multiplier))

        n_variant  = max(1, int(total_count * VARIANT_SPECIFIC_FRACTION))
        n_shared   = total_count - n_variant

        # Shared names — no suffix
        shared_pool = self.rng.sample(vocab, min(n_shared, len(vocab)))
        while len(shared_pool) < n_shared:
            shared_pool.append(
                f"{vocab[len(shared_pool) % len(vocab)]} Variant"
            )

        # Variant-specific names — carry a variant suffix
        suffix = VARIANT_SPECIFIC_SUFFIX[variant_code]
        vs_pool = [
            f"{vocab[i % len(vocab)]}{suffix}"
            for i in range(n_variant)
        ]

        chosen_names = shared_pool + vs_pool

        variant_slug  = self._slug(variant_code)
        assembly_uri  = f"{BASE_NS}assembly_{variant_slug}_{system_key}_{assembly_key}"
        assembly      = Assembly(uri=assembly_uri, name=display_name)

        for idx, pname in enumerate(chosen_names):
            part = self._get_or_create_part(system_key, pname)
            qty  = self.rng.randint(1, 50)
            link_uri = self._next_part_link_uri(assembly_uri, idx)
            assembly.part_links.append(
                PartLink(uri=link_uri, part_uri=part.uri, quantity=qty)
            )
        return assembly

    # ── main build ───────────────────────────────────────────

    def build(self) -> None:
        for code, v_name in VARIANTS.items():
            multiplier  = VARIANT_MULTIPLIER[code]
            variant_slug = self._slug(code)
            vehicle_uri  = f"{BASE_NS}vehicle_{variant_slug}"
            vehicle       = Vehicle(uri=vehicle_uri, code=code, name=v_name)

            for sys_key, sys_spec in SYSTEMS.items():
                sys_uri = f"{BASE_NS}system_{variant_slug}_{sys_key}"
                system  = System(uri=sys_uri, name=sys_spec["name"])

                # Base assemblies
                for asm_key, (asm_name, count_range) in sys_spec["assemblies"].items():
                    asm = self._build_assembly(
                        code, sys_key, asm_key, asm_name, count_range, multiplier
                    )
                    system.assemblies.append(asm)

                # Variant-specific extra assemblies
                extras = VARIANT_EXTRA_ASSEMBLIES.get(code, {}).get(sys_key, [])
                for (asm_key, asm_name, count_range) in extras:
                    asm = self._build_assembly(
                        code, sys_key, asm_key, asm_name, count_range, multiplier
                    )
                    system.assemblies.append(asm)

                vehicle.systems.append(system)

            self.vehicles.append(vehicle)

        # ── Enforce ≥20 % shared parts ────────────────────────
        # The _part_pool already makes identical part names reuse the same URI.
        # To guarantee ≥20 % sharing we additionally inject a set of truly
        # cross-variant "platform parts" that are wired into every variant's
        # first assembly of each system.
        self._inject_platform_parts()

    def _inject_platform_parts(self) -> None:
        """Ensure ≥20 % of parts are shared across ≥2 variants."""
        # Pick 100 platform parts (one per system, several per system)
        platform_parts: list[tuple[str, str]] = []  # (sys_key, part_name)
        for sys_key in SYSTEMS:
            vocab = PART_VOCAB[sys_key]
            picks = self.rng.sample(vocab, min(15, len(vocab)))
            platform_parts.extend((sys_key, p) for p in picks)

        # Wire each platform part into every variant's first assembly in its system
        for sys_key, pname in platform_parts:
            part = self._get_or_create_part(sys_key, pname)
            for vehicle in self.vehicles:
                for system in vehicle.systems:
                    if system.name == SYSTEMS[sys_key]["name"]:
                        # Insert into first assembly if not already present
                        asm = system.assemblies[0]
                        existing_part_uris = {pl.part_uri for pl in asm.part_links}
                        if part.uri not in existing_part_uris:
                            idx      = len(asm.part_links)
                            link_uri = self._next_part_link_uri(asm.uri, idx)
                            qty      = self.rng.randint(1, 4)
                            asm.part_links.append(
                                PartLink(uri=link_uri, part_uri=part.uri, quantity=qty)
                            )
                        break

    # ── statistics ───────────────────────────────────────────

    def stats(self) -> dict:
        total_unique = len(self.parts)
        # Count parts referenced by ≥2 distinct vehicles
        part_to_variants: dict[str, set[str]] = {}
        for v in self.vehicles:
            for s in v.systems:
                for a in s.assemblies:
                    for pl in a.part_links:
                        part_to_variants.setdefault(pl.part_uri, set()).add(v.code)
        shared = sum(1 for vset in part_to_variants.values() if len(vset) >= 2)
        pct    = shared / total_unique * 100 if total_unique else 0
        return {
            "unique_parts": total_unique,
            "shared_parts": shared,
            "shared_pct":   pct,
            "vehicles":     len(self.vehicles),
        }

# ─────────────────────────────────────────────────────────────
#  Turtle serialiser
# ─────────────────────────────────────────────────────────────

def ttl_literal_string(text: str) -> str:
    """Escape a string for Turtle string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

def ttl_decimal(value: float) -> str:
    return f'"{value:.4f}"^^<{XSD_NS}decimal>'

def ttl_integer(value: int) -> str:
    return f'"{value}"^^<{XSD_NS}integer>'

def ttl_string(value: str) -> str:
    return f'"{ttl_literal_string(value)}"^^<{XSD_NS}string>'

def serialise_turtle(gen: BomGenerator) -> str:
    lines: list[str] = []
    a = lines.append

    # Prefixes
    a(f"@prefix bom:  <{ONT_NS}> .")
    a(f"@prefix data: <{BASE_NS}> .")
    a(f"@prefix rdf:  <{RDF_NS}> .")
    a(f"@prefix xsd:  <{XSD_NS}> .")
    a("")

    # ── Parts ─────────────────────────────────────────────────
    a("# ─── Parts ──────────────────────────────────────────────────")
    for part in gen.parts.values():
        a(f"<{part.uri}>")
        a(f"    rdf:type          bom:Part ;")
        a(f"    bom:partName      {ttl_string(part.name)} ;")
        a(f"    bom:partNumber    {ttl_string(part.number)} ;")
        a(f"    bom:unitCostGBP   {ttl_decimal(part.unit_cost)} ;")
        a(f"    bom:unitWeightKg  {ttl_decimal(part.unit_weight)} .")
        a("")

    # ── Vehicles, Systems, Assemblies, PartLinks ───────────────
    a("# ─── Vehicles ───────────────────────────────────────────────")
    for vehicle in gen.vehicles:
        a(f"<{vehicle.uri}>")
        a(f"    rdf:type          bom:Vehicle ;")
        a(f"    bom:variantCode   {ttl_string(vehicle.code)} ;")
        a(f"    bom:vehicleName   {ttl_string(vehicle.name)} ;")
        sys_uris = " ,\n                      ".join(
            f"<{s.uri}>" for s in vehicle.systems
        )
        a(f"    bom:hasSystem     {sys_uris} .")
        a("")

    a("# ─── Systems ────────────────────────────────────────────────")
    for vehicle in gen.vehicles:
        for system in vehicle.systems:
            a(f"<{system.uri}>")
            a(f"    rdf:type          bom:System ;")
            a(f"    bom:systemName    {ttl_string(system.name)} ;")
            asm_uris = " ,\n                      ".join(
                f"<{asm.uri}>" for asm in system.assemblies
            )
            a(f"    bom:hasAssembly   {asm_uris} .")
            a("")

    a("# ─── Assemblies & PartLinks ─────────────────────────────────")
    for vehicle in gen.vehicles:
        for system in vehicle.systems:
            for asm in system.assemblies:
                a(f"<{asm.uri}>")
                a(f"    rdf:type          bom:Assembly ;")
                a(f"    bom:assemblyName  {ttl_string(asm.name)} ;")
                link_uris = " ,\n                      ".join(
                    f"<{pl.uri}>" for pl in asm.part_links
                )
                a(f"    bom:hasPart       {link_uris} .")
                a("")

                for pl in asm.part_links:
                    a(f"<{pl.uri}>")
                    a(f"    rdf:type          bom:PartLink ;")
                    a(f"    bom:part          <{pl.part_uri}> ;")
                    a(f"    bom:quantity      {ttl_integer(pl.quantity)} .")
                    a("")

    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate apex_bom.ttl — synthetic automotive BOM RDF dataset"
    )
    parser.add_argument(
        "--out", default="apex_bom.ttl",
        help="Output file path (default: apex_bom.ttl)"
    )
    parser.add_argument(
        "--seed", type=int, default=SEED,
        help=f"Random seed (default: {SEED})"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Print dataset statistics and exit without writing file"
    )
    args = parser.parse_args()

    print("Generating Apex Meridian BOM …", file=sys.stderr)
    gen = BomGenerator(seed=args.seed)
    gen.build()

    st = gen.stats()
    print(
        f"  Variants    : {st['vehicles']}\n"
        f"  Unique parts: {st['unique_parts']}\n"
        f"  Shared parts: {st['shared_parts']} ({st['shared_pct']:.1f} %)",
        file=sys.stderr,
    )

    if st["unique_parts"] < 400:
        print(
            f"WARNING: only {st['unique_parts']} unique parts generated "
            f"(requirement: ≥400). Increase PART_VOCAB or part counts.",
            file=sys.stderr,
        )

    if st["shared_pct"] < 20.0:
        print(
            f"WARNING: shared-part percentage is {st['shared_pct']:.1f} % "
            f"(requirement: ≥20 %). Increase platform part injection.",
            file=sys.stderr,
        )

    if args.stats:
        return

    out_path = Path(args.out)
    print(f"Serialising Turtle to {out_path} …", file=sys.stderr)
    turtle = serialise_turtle(gen)
    out_path.write_text(turtle, encoding="utf-8")
    print(f"Done — {out_path} written ({out_path.stat().st_size:,} bytes).", file=sys.stderr)

    print(
        "\nNext steps:\n"
        "  1. Start Fuseki:  docker run -d -p 3030:3030 -e ADMIN_PASSWORD=admin "
        "-v $(pwd)/fuseki-data:/fuseki --name apex-bom stain/jena-fuseki:latest\n"
        "  2. Create dataset via http://localhost:3030 (name: apex-bom)\n"
        "  3. Load data:\n"
        "       import requests\n"
        "       with open('apex_bom.ttl', 'rb') as f:\n"
        "           requests.post('http://localhost:3030/apex-bom/data',\n"
        "               data=f, headers={'Content-Type':'text/turtle'},\n"
        "               auth=('admin','admin'))\n"
        "  4. Verify: SELECT (COUNT(*) AS ?triples) WHERE { ?s ?p ?o }",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
