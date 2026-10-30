# Plants, analytics and the greenhouse map

## Plant knowledgebase (Plants page)

Eight built-in profiles: tomato, cucumber, sweet pepper, lettuce, spinach, basil (herbs), strawberry, eggplant. Each has temperature (day/night), humidity, VPD, DLI, **separate soil and hydroponic profiles** (pH, EC, solution temperature), germination, planting, transplanting, growth stages, harvest, common pests, diseases and disorders, and qualitative nutrient notes.

**Provenance, please read:** the numbers are *general horticultural guidance*: broad ranges commonly cited in greenhouse practice, entered without a local trial. They are **not verified** for your cultivar, substrate or climate and not locally verified recommendations. Every page says so. You can change any numeric range; changed fields are marked **yours** and the rest stay general guidance (reset any time). Water demand is intentionally empty: set your own figure.

Custom crops: duplicate a profile as your own, or `PUT /api/plants/{id}`. Herbs other than basil need their own profile.

Setpoints: `GET /api/plants/{id}/setpoints` derives starting values for the Climate setpoint template from the profile. The hysteresis and fan offset it applies are assumptions, shown as such.

## Crop batches and harvests

Record what is planted where (crop, method, area, planting date, stage), then harvests (kg). Yield per m² is calculated from your records. **Conditions** compares live readings with the batch's profile (temperature judged day/night by clock time, humidity, VPD, and for hydroponic batches solution pH/EC/temperature): *in range / low / high / no data*. Missing data never shows as OK.

## VPD and DLI

- **VPD** = saturation vapour pressure at air temperature minus actual, assuming leaf temperature equals air temperature (a simplification). The Analytics chart shades the target band of the newest active batch or the crop you pick.
- **DLI** is the PAR sensor reading integrated over the local day (µmol m⁻² s⁻¹ × seconds ÷ 10⁶). It includes light from your own fixtures. Gaps over 5 minutes are not integrated, and days with under 90% coverage are shown as incomplete and not judged against targets. Lux is never converted.

## Reports and exports

Daily, weekly (Mon-Sun) and monthly reports as JSON, CSV and PDF: climate min/avg/max, VPD, CO₂, outdoor temperature, DLI per day, time inside the crop's VPD/humidity/temperature bands, irrigation (runs, **measured** litres from flow sensors only, estimated litres from your expected flow, aborted runs), lighting energy (needs a power sensor on a lighting program), alert counts and a data-completeness figure. A **condensation indicator** (share of samples with the greenhouse dew point at or above the outdoor temperature) is provided as an indicator only. Seasonal comparison shows monthly means per year; it fills in as data accumulates and data past the retention period is gone. Raw measurements export per sensor as CSV.

Energy: only lighting energy with a power sensor is recorded; heating, pumps and fans are not metered.

## Greenhouse map (Map page)

2D designer of the drawing area (the longer side horizontal). Palette: soil/hydroponic beds, walkways, doors, tanks, pipes, valves, drains, climate and soil sensors, fans, vents, heaters, lights, control cabinet, cable routes. Drag to move, red handle or numeric fields to resize, rotate 90°, duplicate, delete, grid snap. Items can link to sensors, outputs, windows, zones or tanks; linked sensors show **live readings** and soil beds linked to a soil-moisture sensor are coloured by moisture. Layers (climate, soil moisture, irrigation, lighting, electrical, equipment) toggle independently. Save stores the layout; export PNG/SVG from the browser or PDF from the server (optionally with live readings and only the visible layers). The map is a drawing aid: it does not generate irrigation or wiring designs.
