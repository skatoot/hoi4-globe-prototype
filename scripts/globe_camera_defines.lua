-- HOI4 1.19.3 graphics-only overview controls.
-- Install as common/defines/zz_globe_camera.lua after 00_graphics.lua.
-- Every key below exists in the installed game's graphics define table.

-- The same native map-camera constructor reads these bounds for both
-- the front end and gameplay. Keep the height below the initial far plane.
NDefines.NFrontend.CAMERA_MIN_HEIGHT = 50.0
NDefines.NFrontend.CAMERA_MAX_HEIGHT = 3600.0

-- Start farther above Europe and face almost straight down. These keys
-- set the main-menu camera; saved games / country clicks can recenter it.
NDefines.NFrontend.CAMERA_START_Y = 1800.0
NDefines.NFrontend.CAMERA_END_Y = 1950.0
NDefines.NFrontend.CAMERA_START_Z = 1480.0
NDefines.NFrontend.CAMERA_END_Z = 1500.0
NDefines.NFrontend.CAMERA_INTERPOLATION_SPEED = 0.14

-- Moderate wheel acceleration makes it easier to settle at orbital zoom.
NDefines.NGraphics.CAMERA_ZOOM_SPEED = 35
NDefines.NGraphics.CAMERA_ZOOM_KEY_SCALE = 0.015
NDefines.NGraphics.CAMERA_ZOOM_SPEED_DISTANCE_MULT = 3.0

-- This is the native minimum altitude for map names. The globe label
-- shader supplies the upper altitude fade, keeping orbital views clear.
NDefines.NGraphics.DRAW_COUNTRY_NAMES_CUTOFF = 80
