#!/usr/bin/env python3

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import subprocess
import platform
import time

from loguru import logger
import orjson
import httpx


@dataclass
class GpuInfoStreamer:
    """Send nvidia GPU performance details to a victoria metrics server"""

    # where to push metrics
    # NOTE: we are PUSHING metrics not opening up service endpoint for reading
    host: str = "http://localhost:8428"

    # fetch metrics every 10 milliseconds by default
    ms: str | int = 10

    # collect 1,000 batches of readings by default
    batch_size: int = 1000

    def __post_init__(self):
        # create our data holders
        self.timestamps = []
        self.values = defaultdict(list)

        # verify our time is a number then make it a string for the processing to consume
        self.ms = str(int(self.ms))

        # important: this MUST match the order of command arguments to `nvidia-smi` in the `subprocess.Popen`
        self.metric_name_list = [
            "pstate",
            "power_management",
            "power_draw",
            "power_draw_average",
            "power_draw_instant",
            "power_limit",
            "power_default_limit",
            "power_min_limit",
            "power_max_limit",
            "temperature_gpu",
            "temperature_memory",
            "memory_used",
            "memory_total",
            "memory_free",
            "current_clocks",
            "current_memory_clocks",
            "throttle_reasons_supported",
            "throttle_reasons_active",
            "throttle_reasons_gpu_idle",
            "throttle_reasons_applications_clocks_setting",
            "throttle_reasons_sw_power_cap",
            "throttle_reasons_hw_slowdown",
            "throttle_reasons_hw_thermal_slowdown",
            "throttle_reasons_hw_power_brake_slowdown",
            "throttle_reasons_sw_thermal_slowdown",
            "throttle_reasons_sync_boost",
        ]

        # create the victoria metrics import URL
        self.url = self.host + "/api/v1/import"

        # you can have a lil client, as a treat
        self.client = httpx.Client()

        logger.opt(depth=5).info(
            "Sending remote metrics every {:,.2f} seconds (reading {} ms; batching {} metrics per-send)",
            int(self.ms) / 1000 * self.batch_size,
            self.ms,
            self.batch_size,
        )
        logger.opt(depth=5).info(
            "[{}] Created agent for sending GPU stats...",
            self.url,
        )

    def mkmetric(self, name, job, instance):
        """Generate the victoria metrics import JSON format for current `name` metric data"""
        return {
            "metric": {"__name__": name, "job": job, "instance": instance},
            "values": self.values[name],
            "timestamps": self.timestamps,
        }

    def send_batch(self, job="nvidia-smi", instance=platform.node()):
        """Send the currently cached metrics to the metrics server."""
        metrics_built = [
            self.mkmetric(metric, job, instance) for metric in self.metric_name_list
        ]

        # API format is newlines JSON, not a single JSON object or array itself.
        # https://docs.victoriametrics.com/Single-server-VictoriaMetrics.html#how-to-export-data-in-json-line-format
        # https://docs.victoriametrics.com/Single-server-VictoriaMetrics.html#how-to-import-data-in-native-format
        data = b"\n".join([orjson.dumps(j) for j in metrics_built])

        logger.info(
            "[metrics {}, batch size {}] Sending metrics...",
            len(metrics_built),
            len(self.timestamps),
        )
        response = self.client.post(self.url, data=data)

        # only clear metrics if the receiver accepted them!
        # otherwise, will retry  next time just with a larger send batch...
        # (also, the victoria metrics endpoint doesn't report success/failure, so 204 is "eh something happened!")
        if response.status_code in {200, 204}:
            # reset for next cycle...
            self.timestamps.clear()
            self.values.clear()
        else:
            logger.warning("Sending failed? Received: {}", response)

    def stream_gpu_info(self):
        """Run `nvidia-smi` in CSV streaming mode to fetch statistics then send to the metrics endpoint"""
        # for details of their fields and meanings, use:
        # nvidia-smi --help-query-gpu

        # NOTE: the order of fields here MUST match their names in `self.metric_name_list`
        process = subprocess.Popen(
            [
                "nvidia-smi",
                "-lms",
                self.ms,
                "--query-gpu=pstate,power.management,power.draw,power.draw.average,power.draw.instant,power.limit,power.default_limit,power.min_limit,power.max_limit,"
                "temperature.gpu,temperature.memory,"
                "memory.used,memory.total,memory.free,"
                "clocks.current.sm,clocks.current.memory,"
                "clocks_throttle_reasons.supported,clocks_throttle_reasons.active,"
                "clocks_throttle_reasons.gpu_idle,clocks_throttle_reasons.applications_clocks_setting,"
                "clocks_throttle_reasons.sw_power_cap,clocks_throttle_reasons.hw_slowdown,"
                "clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.hw_power_brake_slowdown,"
                "clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.sync_boost,"
                "timestamp",
                "--format=csv,nounits",
            ],
            stdout=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        )

        try:
            # skip header row
            process.stdout.readline()

            count = 0
            for line in iter(process.stdout.readline, ""):
                gpu_info = line.strip().split(", ")

                pstate = int(gpu_info[0][1])
                power_management = 1 if "Enabled" in gpu_info[1] else 0
                power_draw = float(gpu_info[2])
                power_draw_average = float(gpu_info[3])
                power_draw_instant = float(gpu_info[4])
                power_limit = float(gpu_info[5])
                power_default_limit = float(gpu_info[6])
                power_min_limit = float(gpu_info[7])
                power_max_limit = float(gpu_info[8])
                temperature_gpu = float(gpu_info[9])
                temperature_memory = float(gpu_info[10])
                memory_used = float(gpu_info[11])
                memory_total = float(gpu_info[12])
                memory_free = float(gpu_info[13])
                current_clocks = float(gpu_info[14])
                current_memory_clocks = float(gpu_info[15])
                throttle_reasons_supported = 0 if "Not" in gpu_info[16] else 1
                throttle_reasons_active = 0 if "Not" in gpu_info[17] else 1
                throttle_reasons_gpu_idle = 0 if "Not" in gpu_info[18] else 1
                throttle_reasons_applications_clocks_setting = (
                    0 if "Not" in gpu_info[19] else 1
                )
                throttle_reasons_sw_power_cap = 0 if "Not" in gpu_info[20] else 1
                throttle_reasons_hw_slowdown = 0 if "Not" in gpu_info[21] else 1
                throttle_reasons_hw_thermal_slowdown = 0 if "Not" in gpu_info[22] else 1
                throttle_reasons_hw_power_brake_slowdown = (
                    0 if "Not" in gpu_info[23] else 1
                )
                throttle_reasons_sw_thermal_slowdown = 0 if "Not" in gpu_info[24] else 1
                throttle_reasons_sync_boost = 0 if "Not" in gpu_info[25] else 1

                metrics_list = [
                    pstate,
                    power_management,
                    power_draw,
                    power_draw_average,
                    power_draw_instant,
                    power_limit,
                    power_default_limit,
                    power_min_limit,
                    power_max_limit,
                    temperature_gpu,
                    temperature_memory,
                    memory_used,
                    memory_total,
                    memory_free,
                    current_clocks,
                    current_memory_clocks,
                    throttle_reasons_supported,
                    throttle_reasons_active,
                    throttle_reasons_gpu_idle,
                    throttle_reasons_applications_clocks_setting,
                    throttle_reasons_sw_power_cap,
                    throttle_reasons_hw_slowdown,
                    throttle_reasons_hw_thermal_slowdown,
                    throttle_reasons_hw_power_brake_slowdown,
                    throttle_reasons_sw_thermal_slowdown,
                    throttle_reasons_sync_boost,
                ]

                # use timestamp from CSV row instead of just guessing locally
                # (because our parsing here can be offset a little from actual rows due
                #  to the sync http.post updates)
                when = datetime.strptime(
                    gpu_info[-1], "%Y/%m/%d %H:%M:%S.%f"
                ).timestamp()
                self.timestamps.append(int(when * 1000))

                count += 1

                for metric_name, metric_value in zip(
                    self.metric_name_list, metrics_list
                ):
                    self.values[metric_name].append(metric_value)

                if count % self.batch_size == 0:
                    self.send_batch()
                elif count % 100 == 0:
                    logger.info("Received datapoints: {}", count)

        except subprocess.CalledProcessError:
            raise
        except KeyboardInterrupt:
            logger.warning("Goodbye!")
        finally:
            # send any remaining batch (if we have data)...
            if self.timestamps:
                self.send_batch()

            process.stdout.close()
            process.wait()
            self.client.close()


def cmd():
    import fire

    fire.Fire(GpuInfoStreamer)


if __name__ == "__main__":
    cmd()
