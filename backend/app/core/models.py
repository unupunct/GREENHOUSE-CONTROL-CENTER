"""SQLAlchemy tables. Timestamps are integer UTC epoch seconds."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON
    updated_at: Mapped[int] = mapped_column(Integer)


class Sensor(Base):
    """Hardware registry entry for one measured quantity."""

    __tablename__ = "sensors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))  # temperature, humidity, co2, ...
    zone: Mapped[str] = mapped_column(String(32))  # greenhouse, soil, hydroponic, outdoor
    unit: Mapped[str] = mapped_column(String(16))
    driver: Mapped[str] = mapped_column(String(32))  # simulated, (later) modbus_rtu, ...
    protocol: Mapped[str] = mapped_column(String(32))  # informational
    address: Mapped[str] = mapped_column(Text, default="{}")  # JSON driver parameters
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_valid: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_valid: Mapped[float | None] = mapped_column(Float, nullable=True)
    # calibrated = cal_gain * raw + cal_offset
    cal_offset: Mapped[float] = mapped_column(Float, default=0.0)
    cal_gain: Mapped[float] = mapped_column(Float, default=1.0)
    calibrated_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Calibration(Base):
    """Append-only calibration history."""

    __tablename__ = "calibrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[str] = mapped_column(ForeignKey("sensors.id", ondelete="CASCADE"), index=True)
    ts: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(16))  # manual, one_point, two_point, reset
    offset: Mapped[float] = mapped_column(Float)
    gain: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")


class Measurement(Base):
    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[str] = mapped_column(ForeignKey("sensors.id", ondelete="CASCADE"))
    ts: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)

    __table_args__ = (Index("ix_meas_sensor_ts", "sensor_id", "ts"), Index("ix_meas_ts", "ts"))


class Offer(Base):
    """A supplier price for a bill-of-materials item. Entered by the user or
    recorded after checking the supplier page; never generated."""

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String(48), index=True)
    supplier_id: Mapped[str] = mapped_column(String(48))
    product_name: Mapped[str] = mapped_column(String(200), default="")
    manufacturer: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    price_ron: Mapped[float] = mapped_column(Float)
    includes_vat: Mapped[bool] = mapped_column(Boolean, default=True)
    url: Mapped[str] = mapped_column(Text, default="")
    availability: Mapped[str] = mapped_column(String(120), default="")
    delivery: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16))  # verified | user_estimate
    checked_at: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")


class Purchase(Base):
    __tablename__ = "purchases"

    item_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[int] = mapped_column(Integer)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(Integer, index=True)
    level: Mapped[str] = mapped_column(String(16))  # info, warning, error
    source: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(Integer, index=True)
    severity: Mapped[str] = mapped_column(String(16))  # warning, critical
    code: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class Actuator(Base):
    """Switched output. ``max_runtime_s`` is mandatory: a hard ceiling the
    engine enforces regardless of what requested the output."""

    __tablename__ = "actuators"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # pump, valve, dosing, other
    driver: Mapped[str] = mapped_column(String(32))
    address: Mapped[str] = mapped_column(Text, default="{}")
    max_runtime_s: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    feedback_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # climate outputs: {"requires_on":[ids], "forbids_on":[ids], "min_on_s":n, "min_off_s":n,
    #                   "stop_if":{"sensor_id":..,"above":x}, "windows_max_open_pct":x}
    interlocks: Mapped[str] = mapped_column(Text, default="{}")


class Tank(Base):
    __tablename__ = "tanks"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    level_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    float_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 1 = water OK
    min_level_pct: Mapped[float] = mapped_column(Float, default=15.0)


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # soil, hydroponic
    valve_id: Mapped[str] = mapped_column(String(48))
    pump_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    tank_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    flow_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_duration_s: Mapped[int] = mapped_column(Integer)
    default_duration_s: Mapped[int] = mapped_column(Integer, default=300)
    min_interval_s: Mapped[int] = mapped_column(Integer, default=3600)
    expected_flow_lpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_flow_lpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_flow_lpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    flow_grace_s: Mapped[int] = mapped_column(Integer, default=20)
    moisture_sensor_ids: Mapped[str] = mapped_column(Text, default="[]")
    moisture_start_below: Mapped[float | None] = mapped_column(Float, nullable=True)
    moisture_stop_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    schedule: Mapped[str] = mapped_column(Text, default="[]")  # [{days:[0-6], time:"HH:MM", duration_s}]


class IrrigationRun(Base):
    __tablename__ = "irrigation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone_id: Mapped[str] = mapped_column(String(48), index=True)
    source: Mapped[str] = mapped_column(String(16))  # manual, schedule, moisture
    start_ts: Mapped[int] = mapped_column(Integer, index=True)
    end_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_s: Mapped[int] = mapped_column(Integer)
    actual_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_l: Mapped[float | None] = mapped_column(Float, nullable=True)  # measured by flow sensor only
    volume_estimate_l: Mapped[float | None] = mapped_column(Float, nullable=True)  # expected_flow x time
    end_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)


class CommissioningRecord(Base):
    __tablename__ = "commissioning"

    check_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    auto_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    auto_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_detail: Mapped[str] = mapped_column(Text, default="")
    auto_hash: Mapped[str] = mapped_column(String(64), default="")
    manual_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_note: Mapped[str] = mapped_column(Text, default="")
    manual_hash: Mapped[str] = mapped_column(String(64), default="")


class ClimateRule(Base):
    __tablename__ = "climate_rules"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    match: Mapped[str] = mapped_column(String(4), default="all")  # all | any
    conditions: Mapped[str] = mapped_column(Text, default="[]")
    actions: Mapped[str] = mapped_column(Text, default="[]")
    on_delay_s: Mapped[int] = mapped_column(Integer, default=0)
    off_delay_s: Mapped[int] = mapped_column(Integer, default=0)
    min_on_s: Mapped[int] = mapped_column(Integer, default=0)
    min_off_s: Mapped[int] = mapped_column(Integer, default=0)
    max_on_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooldown_s: Mapped[int] = mapped_column(Integer, default=0)
    notify: Mapped[bool] = mapped_column(Boolean, default=False)
    on_fault: Mapped[str] = mapped_column(String(8), default="off")  # off | hold
    generated: Mapped[bool] = mapped_column(Boolean, default=False)


class Window(Base):
    """Motorised opening (vent window or shade screen) driven by two outputs."""

    __tablename__ = "windows"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(8), default="vent")  # vent | shade
    open_output_id: Mapped[str] = mapped_column(String(48))
    close_output_id: Mapped[str] = mapped_column(String(48))
    travel_time_s: Mapped[float] = mapped_column(Float)
    open_limit_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_limit_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rain_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)   # 1 = raining
    wind_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wind_max_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_step_pct: Mapped[float] = mapped_column(Float, default=5.0)
    min_rest_s: Mapped[float] = mapped_column(Float, default=30.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LightProgram(Base):
    __tablename__ = "light_programs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    output_ids: Mapped[str] = mapped_column(Text, default="[]")
    mode: Mapped[str] = mapped_column(String(12), default="photoperiod")  # photoperiod | dli
    start_time: Mapped[str] = mapped_column(String(5), default="06:00")
    photoperiod_h: Mapped[float] = mapped_column(Float, default=16.0)
    ppfd_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dli_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    on_below_ppfd: Mapped[float | None] = mapped_column(Float, nullable=True)
    off_above_ppfd: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DailyStat(Base):
    __tablename__ = "daily_stats"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)


class PlantUser(Base):
    """User changes to a built-in crop profile (patch) or a complete custom crop."""

    __tablename__ = "plant_user"

    crop_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    data: Mapped[str] = mapped_column(Text)  # JSON
    custom: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[int] = mapped_column(Integer)


class CropBatch(Base):
    __tablename__ = "crop_batches"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    crop_id: Mapped[str] = mapped_column(String(48))
    label: Mapped[str] = mapped_column(String(120), default="")
    method: Mapped[str] = mapped_column(String(12))  # soil | hydroponic
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    planted_on: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    stage: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | harvested | discarded
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(Integer)


class Harvest(Base):
    __tablename__ = "harvests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("crop_batches.id", ondelete="CASCADE"), index=True)
    date: Mapped[str] = mapped_column(String(10))
    quantity_kg: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(24))  # calibration|filter|pump|valve|fan|window|safety|battery|storage|backup|other
    subject_kind: Mapped[str] = mapped_column(String(12), default="system")  # sensor|actuator|tank|system
    subject_id: Mapped[str] = mapped_column(String(64), default="")
    interval_days: Mapped[int] = mapped_column(Integer)
    last_done_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class MaintenanceLog(Base):
    __tablename__ = "maintenance_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(48), index=True)
    ts: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")


class Replacement(Base):
    """Equipment replacement history."""

    __tablename__ = "replacements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(Integer, index=True)
    subject_kind: Mapped[str] = mapped_column(String(12))
    subject_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(160), default="")
    old_item: Mapped[str] = mapped_column(String(160), default="")
    new_item: Mapped[str] = mapped_column(String(160), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(12))  # admin | operator | viewer
    created_at: Mapped[int] = mapped_column(Integer)
    last_login_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthSession(Base):
    """Only a SHA-256 of the session token is stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    last_seen: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str] = mapped_column(String(64), default="")
    agent: Mapped[str] = mapped_column(String(160), default="")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String(48), default="")
    role: Mapped[str] = mapped_column(String(12), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(200))
    status: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(String(200), default="")


class MeasurementHourly(Base):
    """Hourly roll-up kept long after raw samples are pruned (seasonal comparison)."""

    __tablename__ = "measurement_hourly"

    sensor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hour_ts: Mapped[int] = mapped_column(Integer, primary_key=True)
    n: Mapped[int] = mapped_column(Integer)
    vmin: Mapped[float] = mapped_column(Float)
    vmax: Mapped[float] = mapped_column(Float)
    vavg: Mapped[float] = mapped_column(Float)
