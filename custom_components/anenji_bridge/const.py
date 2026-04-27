"""Constants for the Anenji Inverter Bridge integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)

DOMAIN: Final = "anenji_bridge"
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
DEFAULT_PORT: Final = 9999
CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 1

MANUFACTURER: Final = "Anenji / SRNE"


# ---------------------------------------------------------------------------
# Sensor entity descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class AnenjiBridgeSensorDescription(SensorEntityDescription):
    """Describe an Anenji Bridge sensor."""

    json_key: str


SENSOR_DESCRIPTIONS: tuple[AnenjiBridgeSensorDescription, ...] = (
    # --- Battery ---
    AnenjiBridgeSensorDescription(
        key="batt_soc",
        json_key="batt_soc",
        name="Battery SOC",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    AnenjiBridgeSensorDescription(
        key="batt_volt",
        json_key="batt_volt",
        name="Battery Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="batt_current",
        json_key="batt_current",
        name="Battery Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="batt_power_watt",
        json_key="batt_power_watt",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- PV / Solar ---
    AnenjiBridgeSensorDescription(
        key="pv_input_watt",
        json_key="pv_input_watt",
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
    ),
    AnenjiBridgeSensorDescription(
        key="pv_input_volt",
        json_key="pv_input_volt",
        name="PV Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="pv_current",
        json_key="pv_current",
        name="PV Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="pv_charging_watt",
        json_key="pv_charging_watt",
        name="PV Charging Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power-variant",
    ),
    # --- Grid ---
    AnenjiBridgeSensorDescription(
        key="grid_power_watt",
        json_key="grid_power_watt",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="grid_volt",
        json_key="grid_volt",
        name="Grid Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="grid_freq",
        json_key="grid_freq",
        name="Grid Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="grid_current",
        json_key="grid_current",
        name="Grid Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Load ---
    AnenjiBridgeSensorDescription(
        key="ac_load_real_watt",
        json_key="ac_load_real_watt",
        name="House Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-lightning-bolt",
    ),
    AnenjiBridgeSensorDescription(
        key="ac_load_va",
        json_key="ac_load_va",
        name="House Load Apparent Power",
        native_unit_of_measurement="VA",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="ac_load_pct",
        json_key="ac_load_pct",
        name="Inverter Load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
    ),
    # --- Output ---
    AnenjiBridgeSensorDescription(
        key="ac_out_volt",
        json_key="ac_out_volt",
        name="Output Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="ac_out_amp",
        json_key="ac_out_amp",
        name="Output Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Temperature ---
    AnenjiBridgeSensorDescription(
        key="temp_dc",
        json_key="temp_dc",
        name="DC/Heatsink Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnenjiBridgeSensorDescription(
        key="temp_inv",
        json_key="temp_inv",
        name="Inverter Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Status (text) ---
    AnenjiBridgeSensorDescription(
        key="device_status_msg",
        json_key="device_status_msg",
        name="Inverter Status",
        icon="mdi:information-outline",
    ),
    AnenjiBridgeSensorDescription(
        key="fault_msg",
        json_key="fault_msg",
        name="Fault Message",
        icon="mdi:alert-circle",
    ),
    AnenjiBridgeSensorDescription(
        key="warning_msg",
        json_key="warning_msg",
        name="Warning Message",
        icon="mdi:alert",
    ),
    # --- Energy (cumulative kWh) ---
    AnenjiBridgeSensorDescription(
        key="total_pv_energy_kwh",
        json_key="total_pv_energy_kwh",
        name="Solar Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
    ),
    AnenjiBridgeSensorDescription(
        key="total_grid_input_kwh",
        json_key="total_grid_input_kwh",
        name="Grid Import Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:transmission-tower",
    ),
    AnenjiBridgeSensorDescription(
        key="total_load_kwh",
        json_key="total_load_kwh",
        name="House Load Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:home-lightning-bolt",
    ),
    AnenjiBridgeSensorDescription(
        key="total_battery_charge_kwh",
        json_key="total_battery_charge_kwh",
        name="Battery Charge Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-charging",
    ),
    AnenjiBridgeSensorDescription(
        key="total_battery_discharge_kwh",
        json_key="total_battery_discharge_kwh",
        name="Battery Discharge Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-minus",
    ),
)


# ---------------------------------------------------------------------------
# Switch entity descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class AnenjiBridgeSwitchDescription(SwitchEntityDescription):
    """Describe an Anenji Bridge switch."""

    json_key: str
    on_value: int | str
    cmd_on: str
    cmd_off: str


SWITCH_DESCRIPTIONS: tuple[AnenjiBridgeSwitchDescription, ...] = (
    AnenjiBridgeSwitchDescription(
        key="backlight",
        json_key="backlight_status",
        name="LCD Backlight",
        icon="mdi:monitor-shimmer",
        on_value=1,
        cmd_on="SET_BACKLIGHT_1",
        cmd_off="SET_BACKLIGHT_0",
    ),
    AnenjiBridgeSwitchDescription(
        key="grid_charging",
        json_key="charger_priority",
        name="Grid Charging",
        icon="mdi:flash",
        on_value=2,
        cmd_on="CHARGE_ON",
        cmd_off="CHARGE_OFF",
    ),
    AnenjiBridgeSwitchDescription(
        key="return_to_default",
        json_key="return_to_default",
        name="Return to Default Screen",
        icon="mdi:arrow-u-left-top",
        on_value=1,
        cmd_on="SET_RETURN_DEFAULT_1",
        cmd_off="SET_RETURN_DEFAULT_0",
    ),
)


# ---------------------------------------------------------------------------
# Number entity descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class AnenjiBridgeNumberDescription(NumberEntityDescription):
    """Describe an Anenji Bridge number."""

    json_key: str
    cmd_prefix: str


NUMBER_DESCRIPTIONS: tuple[AnenjiBridgeNumberDescription, ...] = (
    AnenjiBridgeNumberDescription(
        key="max_ac_amps",
        json_key="max_ac_amps",
        name="Max AC Charge Amps",
        icon="mdi:current-ac",
        native_min_value=5,
        native_max_value=80,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        cmd_prefix="SET_AMPS_",
    ),
    AnenjiBridgeNumberDescription(
        key="max_total_amps",
        json_key="max_total_amps",
        name="Max Total Charge Amps",
        icon="mdi:battery-charging-high",
        native_min_value=10,
        native_max_value=120,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        cmd_prefix="SET_TOTAL_AMPS_",
    ),
    AnenjiBridgeNumberDescription(
        key="soc_back_to_grid",
        json_key="soc_back_to_grid",
        name="Back to Grid SOC",
        icon="mdi:battery-arrow-down",
        native_min_value=4,
        native_max_value=50,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        cmd_prefix="SET_SOC_GRID_",
    ),
    AnenjiBridgeNumberDescription(
        key="soc_back_to_batt",
        json_key="soc_back_to_batt",
        name="Back to Battery SOC",
        icon="mdi:battery-arrow-up",
        native_min_value=60,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        cmd_prefix="SET_SOC_BATT_",
    ),
    AnenjiBridgeNumberDescription(
        key="soc_cutoff",
        json_key="soc_cutoff",
        name="Cut-off SOC",
        icon="mdi:battery-alert",
        native_min_value=3,
        native_max_value=30,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        cmd_prefix="SET_SOC_CUTOFF_",
    ),
    AnenjiBridgeNumberDescription(
        key="bulk_charge_volt",
        json_key="bulk_charge_volt",
        name="Bulk Charge Voltage",
        icon="mdi:battery-arrow-up",
        native_min_value=48.0,
        native_max_value=58.4,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        cmd_prefix="SET_BULK_VOLT_",
    ),
    AnenjiBridgeNumberDescription(
        key="float_charge_volt",
        json_key="float_charge_volt",
        name="Float Charge Voltage",
        icon="mdi:battery-check",
        native_min_value=48.0,
        native_max_value=58.4,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        cmd_prefix="SET_FLOAT_VOLT_",
    ),
    AnenjiBridgeNumberDescription(
        key="low_dc_cutoff_volt",
        json_key="low_dc_cutoff_volt",
        name="Low DC Cut-off Voltage",
        icon="mdi:battery-alert",
        native_min_value=40.0,
        native_max_value=51.9,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        cmd_prefix="SET_LOW_DC_CUTOFF_",
    ),
)


# ---------------------------------------------------------------------------
# Select entity descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class AnenjiBridgeSelectDescription(SelectEntityDescription):
    """Describe an Anenji Bridge select."""

    json_key: str
    options_map: dict[str, str]  # display label → bridge command


SELECT_DESCRIPTIONS: tuple[AnenjiBridgeSelectDescription, ...] = (
    AnenjiBridgeSelectDescription(
        key="output_mode",
        json_key="output_mode",
        name="Output Mode",
        icon="mdi:source-branch",
        options=["Utility First (UTI)", "Solar First (SOL)", "SBU (Solar-Batt-Util)",
                 "SUB (Solar-Util-Batt)", "SUF (GRID Feedback)"],
        options_map={
            "Utility First (UTI)": "MODE_0",
            "Solar First (SOL)": "MODE_1",
            "SBU (Solar-Batt-Util)": "MODE_2",
            "SUB (Solar-Util-Batt)": "MODE_3",
            "SUF (GRID Feedback)": "MODE_4",
        },
    ),
    AnenjiBridgeSelectDescription(
        key="charger_priority",
        json_key="charger_priority",
        name="Charger Priority",
        icon="mdi:battery-charging",
        options=["Solar First (CSO)", "Solar + Utility (SNU)", "Solar Only (OSO)"],
        options_map={
            "Solar First (CSO)": "CSO_SET",
            "Solar + Utility (SNU)": "SNU_SET",
            "Solar Only (OSO)": "OSO_SET",
        },
    ),
    AnenjiBridgeSelectDescription(
        key="buzzer_mode",
        json_key="buzzer_mode",
        name="Buzzer Mode",
        icon="mdi:volume-high",
        options=["Mute", "Source/Warn/Fault", "Warn/Fault", "Fault Only"],
        options_map={
            "Mute": "SET_BUZZER_0",
            "Source/Warn/Fault": "SET_BUZZER_1",
            "Warn/Fault": "SET_BUZZER_2",
            "Fault Only": "SET_BUZZER_3",
        },
    ),
    AnenjiBridgeSelectDescription(
        key="ac_input_range",
        json_key="ac_input_range",
        name="AC Input Range",
        icon="mdi:sine-wave",
        options=["Appliances (APL)", "UPS", "Generator (GEN)"],
        options_map={
            "Appliances (APL)": "SET_AC_RANGE_0",
            "UPS": "SET_AC_RANGE_1",
            "Generator (GEN)": "SET_AC_RANGE_2",
        },
    ),
    AnenjiBridgeSelectDescription(
        key="battery_type",
        json_key="battery_type_code",
        name="Battery Type",
        icon="mdi:battery-sync",
        options=["AGN", "FLD", "USR", "LI2", "LI4", "LIb"],
        options_map={
            "AGN": "SET_BATTERY_TYPE_0",
            "FLD": "SET_BATTERY_TYPE_1",
            "USR": "SET_BATTERY_TYPE_2",
            "LI2": "SET_BATTERY_TYPE_4",
            "LI4": "SET_BATTERY_TYPE_6",
            "LIb": "SET_BATTERY_TYPE_8",
        },
    ),
)


# Reverse lookup: code → display label for selects that use numeric codes
OUTPUT_MODE_MAP: dict[int, str] = {
    0: "Utility First (UTI)",
    1: "Solar First (SOL)",
    2: "SBU (Solar-Batt-Util)",
    3: "SUB (Solar-Util-Batt)",
    4: "SUF (GRID Feedback)",
}

CHARGER_PRIORITY_MAP: dict[int, str] = {
    1: "Solar First (CSO)",
    2: "Solar + Utility (SNU)",
    3: "Solar Only (OSO)",
}

BUZZER_MODE_MAP: dict[int, str] = {
    0: "Mute",
    1: "Source/Warn/Fault",
    2: "Warn/Fault",
    3: "Fault Only",
}

AC_INPUT_RANGE_MAP: dict[int, str] = {
    0: "Appliances (APL)",
    1: "UPS",
    2: "Generator (GEN)",
}

BATTERY_TYPE_MAP: dict[int, str] = {
    0: "AGN",
    1: "FLD",
    2: "USR",
    4: "LI2",
    6: "LI4",
    8: "LIb",
}

# Map json_key → reverse lookup dict
SELECT_REVERSE_MAPS: dict[str, dict[int, str]] = {
    "output_mode": OUTPUT_MODE_MAP,
    "charger_priority": CHARGER_PRIORITY_MAP,
    "buzzer_mode": BUZZER_MODE_MAP,
    "ac_input_range": AC_INPUT_RANGE_MAP,
    "battery_type_code": BATTERY_TYPE_MAP,
}

PLATFORMS: list[str] = ["sensor", "switch", "number", "select"]
