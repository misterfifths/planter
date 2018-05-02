#!/usr/bin/env python

# 2018 / MIT / Tim Clem / github.com/misterfifths
# See LICENSE for details

from __future__ import print_function

from sgp30 import SGP30, AirQuality
from threading import Thread, Timer
from smbus import SMBus
from sys import stderr
from os import path
from time import sleep, time
from blinky import Cougher, Breather
from gsheets import GoogleSheetsLogger


class LoggerThread(Thread):
    def __init__(self):
        Thread.__init__(self)

        self._logger = GoogleSheetsLogger('1xDab4u8O5TgeRMpvSeeBJSj0CfKLsHN8n_1HrdJ3ihs')
        self._pending_log = None
        self._check_interval_seconds = 5
        self.daemon = True

    def run(self):
        try:
            self._logger.setup()
        except Exception as exc:
            print('Error setting up Google sheets logger:', exc, file=stderr)
            return

        while True:
            if self._pending_log is not None:
                try:
                    self._logger.log(self._pending_log)
                    self._pending_log = None
                except Exception as exc:
                    print('Error logging to Google sheets:', exc, file=stderr)

            sleep(self._check_interval_seconds)

    def queue_log(self, air_quality):
        self._pending_log = air_quality


class SensorThread(Thread):
    def __init__(self, smbus, baseline_cache_path=None, baseline_storage_interval=1000):
        Thread.__init__(self)

        self._logger_thread = LoggerThread()

        self._bus = smbus
        self._chip = SGP30(smbus)

        self.last_sample = None
        self.warming_up = True

        self.baseline_cache_path = baseline_cache_path
        self.baseline_storage_interval = baseline_storage_interval
        self._samples_until_baseline_store = baseline_storage_interval

        self.terminate_asap = False

        self.__co2_baseline = self.__voc_baseline = None
        if self.baseline_cache_path:
            try:
                with open(baseline_cache_path) as f:
                    self.__co2_baseline = int(f.readline())
                    self.__voc_baseline = int(f.readline())
            except Exception as exc:
                print('Error loading baseline:', exc, file=stderr)

    def start(self):
        Thread.start(self)
        self._logger_thread.start()

    def run(self):
        if self.terminate_asap:
            return

        self._chip.open()

        try:
            while True:
                if self.terminate_asap:
                    break

                if self.__co2_baseline is not None:
                    self._chip.set_baseline(self.__co2_baseline, self.__voc_baseline)
                    print('Restored baselines', file=stderr)

                self._loop()
        finally:
            self._chip.close()

    def _loop(self):
        sample = self._chip.measure_air_quality()
        if self.warming_up and sample.is_probably_warmup_value():
            return

        self.warming_up = False
        self.last_sample = sample

        self._logger_thread.queue_log(sample)

        if self.terminate_asap:
            return

        self._samples_until_baseline_store = self._samples_until_baseline_store - 1

        if self._samples_until_baseline_store == 0:
            self._samples_until_baseline_store = self.baseline_storage_interval

            try:
                self._store_baselines()
            except Exception as exc:
                print('Error storing baselines:', exc, file=stderr)

    def _store_baselines(self):
        if self.baseline_cache_path:
            baseline = self._chip.get_baseline()
            with open(self.baseline_cache_path, 'w') as f:
                f.write(str(baseline.raw_co2) + "\n" + str(baseline.raw_voc))


class ThePlanter(object):
    def __init__(self):
        self._min_seconds_between_breaths = 10
        self._min_seconds_between_coughs = 5
        self._bad_co2_threshold = 450
        self._bad_voc_threshold = 50

        self._seconds_until_next_breath = 0
        self._seconds_until_next_possible_cough = 0

        self.smbus = SMBus()

        baseline_file = path.join(path.dirname(path.realpath(__file__)), 'sgp30-baseline')
        self.sensor_thread = SensorThread(self.smbus, baseline_cache_path=baseline_file)

        cough_filename = path.join(path.dirname(path.realpath(__file__)), '151217__owlstorm__cough-3.wav')
        self.cougher = Cougher(cough_filename, (360.0, 1.0, 1.0))

        self.breather = Breather((161 / 360.0, 0.98, 1.0))

    def setup(self):
        self.cougher.setup()
        self.smbus.open(1)  # 0 on some devices
        self.sensor_thread.start()

    def teardown(self):
        if self.sensor_thread is None:
            return

        print('Waiting on sensor thread to terminate...', file=stderr)
        self.sensor_thread.terminate_asap = True
        self.sensor_thread.join()
        self.sensor_thread = None

        self.smbus.close()
        self.smbus = None

        self.cougher.teardown()
        self.cougher = None

    def main(self):
        min_sleep_between_loop_calls = 0.2

        try:
            self.smbus.open(1)

            self.sensor_thread.start()

            time_at_start_of_last_loop = time()

            while True:
                now = time()

                loop_res = self.loop(self.sensor_thread.last_sample, now - time_at_start_of_last_loop)

                time_at_start_of_last_loop = now

                if loop_res is False:
                    return

                now = time()
                needed_extra_sleep = min_sleep_between_loop_calls - (now - time_at_start_of_last_loop)
                if needed_extra_sleep >= 0:
                    sleep(needed_extra_sleep)
        except Exception as exc:
            print('Going down:', exc, file=stderr)
        finally:
            self.teardown()

    def loop(self, last_sample, dt):
        print(dt, self._seconds_until_next_breath, self._seconds_until_next_possible_cough, last_sample)

        if last_sample is None:
            return

        is_bad = last_sample.co2_ppm >= self._bad_co2_threshold or last_sample.voc_ppb >= self._bad_voc_threshold

        # always becomes more possible to cough
        self._seconds_until_next_possible_cough = self._seconds_until_next_possible_cough - dt

        if is_bad:
            # a bad sample should reset the time until the next breath
            self._seconds_until_next_breath = self._min_seconds_between_breaths

            if self._seconds_until_next_possible_cough <= 0:
                self.cougher.cough()
                self._seconds_until_next_possible_cough = self._min_seconds_between_coughs
        else:
            # a good sample should get us closer to a breath
            self._seconds_until_next_breath = self._seconds_until_next_breath - dt
            if self._seconds_until_next_breath <= 0:
                self.breather.breathe()
                self._seconds_until_next_breath = self._min_seconds_between_breaths


if __name__ == '__main__':
    planter = ThePlanter()
    try:
        planter.setup()
        planter.main()
    finally:
        planter.teardown()
