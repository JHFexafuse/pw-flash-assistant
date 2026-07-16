# PrintWars multi-zone heated bed support for Klipper
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import re


class PrintWarsMultiBed:
    def __init__(self, config):
        self.printer = config.get_printer()
        raw_heaters = config.get("heaters")
        self.heater_names = [name for name in re.split(r"[,\s]+", raw_heaters) if name]
        if len(self.heater_names) < 2:
            raise config.error("pw_multibed requires at least two configured heaters")
        self.primary_name = config.get("primary", self.heater_names[0])
        if self.primary_name not in self.heater_names:
            raise config.error("pw_multibed primary must be included in heaters")
        self.wait_all = config.getboolean("wait_all", True)
        self.pheaters = None
        self.heaters = []
        self.primary_heater = None
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _handle_connect(self):
        self.pheaters = self.printer.lookup_object("heaters")
        self.heaters = [self.pheaters.lookup_heater(name) for name in self.heater_names]
        self.primary_heater = self.pheaters.lookup_heater(self.primary_name)
        gcode = self.printer.lookup_object("gcode")
        mux = gcode.mux_commands.get("SET_HEATER_TEMPERATURE")
        if mux is None or mux[0] != "HEATER" or self.primary_name not in mux[1]:
            raise self.printer.config_error(
                "pw_multibed could not find SET_HEATER_TEMPERATURE for %s"
                % (self.primary_name,)
            )
        self.original_primary_handler = mux[1][self.primary_name]
        mux[1][self.primary_name] = self.cmd_SET_HEATER_TEMPERATURE
        gcode.register_command("M140", None)
        gcode.register_command("M190", None)
        gcode.register_command("M140", self.cmd_M140)
        gcode.register_command("M190", self.cmd_M190)
        gcode.register_command(
            "MULTIBED_STATUS", self.cmd_MULTIBED_STATUS,
            desc="Reports the PrintWars multibed heater group")

    def _set_all(self, target, wait=False):
        for heater in self.heaters:
            self.pheaters.set_temperature(heater, target)
        if wait and target:
            wait_heaters = self.heaters if self.wait_all else [self.primary_heater]
            for heater in wait_heaters:
                self.pheaters.set_temperature(heater, target, wait=True)

    def cmd_M140(self, gcmd):
        self._set_all(gcmd.get_float("S", 0.0))

    def cmd_M190(self, gcmd):
        self._set_all(gcmd.get_float("S", 0.0), wait=True)

    def cmd_SET_HEATER_TEMPERATURE(self, gcmd):
        self.original_primary_handler(gcmd)
        target = gcmd.get_float("TARGET", 0.0)
        for heater in self.heaters:
            if heater is not self.primary_heater:
                self.pheaters.set_temperature(heater, target)

    def cmd_MULTIBED_STATUS(self, gcmd):
        gcmd.respond_info("Multibed heaters: %s" % (", ".join(self.heater_names),))

    def get_status(self, eventtime):
        return {
            "heaters": list(self.heater_names),
            "primary": self.primary_name,
            "wait_all": self.wait_all,
        }


def load_config(config):
    return PrintWarsMultiBed(config)
