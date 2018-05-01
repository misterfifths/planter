#!/usr/bin/env python

# 2018 / MIT / Tim Clem / github.com/misterfifths
# See LICENSE for details

from __future__ import print_function

from time import sleep
from math import floor, exp, isnan, isinf
import colorsys
from pydub import AudioSegment
import pyaudio
import wave
import blinkt
from os import path

class Helpers(object):
    @classmethod
    def _raw_fade_curve(cls, t):
        flatness_factor = 2.0
        v = exp(flatness_factor * (t - 1) / 2.0) - (1 - 2 * t) * exp(-flatness_factor / 2.0)
        return min(1, max(0, v))

    @classmethod
    def brightness_curve(cls, led_idx, t_pct):
        # center lights should effectively run through the curve faster than the outer ones
        # everyone should do a full curve though, so they all reach max brightness

        distance_from_center = abs(round(led_idx - 3.5))
        pct_dfc = distance_from_center / 4.0
        # pdfc == 0 -> march up to max by t=0.25, stay there until t=0.75, fade out
        # pdfc == 1 -> reach max by t=0.5, fade out immediately

        # values for the center LEDs;
        max_t_to_hold_at_max = 0.5  # tweakable
        min_t_for_one_fade = (1.0 - max_t_to_hold_at_max) / 2.0

        # for the outermost LEDs:
        min_t_to_hold_at_max = 0 # tweakable; must be <= max_t_to_hold_at_max
        max_t_for_one_fade = 0.5  # tweakable; must be >= min_t_for_one_fade

        # pdfc == 0 -> up to max by t=min_t_for_one_fade, stay there until t=min_t_for_one_fade+max_t_to_hold_at_max, fade
        # pdfc == 1 -> up to max by t=max_t_for_one_fade, stay there until t=max_t_for_one_fade+min_t_to_hold_at_max, fade

        t_to_end_fade_in = min_t_for_one_fade + pct_dfc * (max_t_for_one_fade - min_t_for_one_fade)
        t_to_hold_at_max = min_t_to_hold_at_max + (1.0 - pct_dfc) * (max_t_to_hold_at_max - min_t_to_hold_at_max)
        t_to_start_fade_out = t_to_end_fade_in + t_to_hold_at_max
        fade_out_duration = 1.0 - t_to_start_fade_out

        if t_pct < t_to_end_fade_in:
            pct_into_fade = t_pct / t_to_end_fade_in  # 0 -> 1 over fade in duration
            fade_t = pct_into_fade
            return cls._raw_fade_curve(fade_t)

        if t_pct < t_to_start_fade_out:
            return 1.0

        # t >= t_to_start_fade_out
        pct_into_fade = (t_pct - t_to_start_fade_out) / fade_out_duration  # 0 -> 1 over fade out duration
        fade_t = 1.0 - pct_into_fade  # 1 -> 0 (using _raw_fade_curve backwards)
        return cls._raw_fade_curve(fade_t)

    @classmethod
    def set_pixel_hsv(cls, i, hsv_components, brightness=None):
        r_pct, g_pct, b_pct = colorsys.hsv_to_rgb(*hsv_components)
        r = floor(r_pct * 255)
        g = floor(g_pct * 255)
        b = floor(b_pct * 255)

        if brightness is None:
            blinkt.set_pixel(i, r, g, b)
        else:
            blinkt.set_pixel(i, r, g, b, brightness)


class Breather(object):
    def __init__(self, color_hsv, cycle_duration=4, dt=0.1, max_brightness_clamp=0.15, whiteness_factor=0.8):
        self.color_hsv = color_hsv
        self.cycle_duration = cycle_duration
        self.dt = dt
        self.max_brightness_clamp = max_brightness_clamp
        self.whiteness_factor = whiteness_factor

    def breathe(self):
        t = 0

        while True:
            t_pct = min(1.0, t / float(self.cycle_duration))

            for i in range(8):
                brightness = Helpers.brightness_curve(i, t_pct)
                h, s, v = self.color_hsv
                s = s - (s * brightness * self.whiteness_factor)  # go to white as brightness increasses
                Helpers.set_pixel_hsv(i, (h, s, v), brightness * self.max_brightness_clamp)

            blinkt.show()
            sleep(self.dt)

            t = t + self.dt
            if t > self.cycle_duration:
                blinkt.clear()
                blinkt.show()
                return

class Cougher(object):
    def __init__(self, wav_filename, color_hsv, ms_stride_for_volume_samples=20, max_brightness_clamp=0.15, whiteness_factor=0.8):
        self.wav_filename = wav_filename
        self.color_hsv = color_hsv
        self.ms_stride_for_volume_samples = ms_stride_for_volume_samples
        self.max_brightness_clamp = max_brightness_clamp
        self.whiteness_factor = whiteness_factor

        self._cough_volumes = None
        self._cough_waveform = None
        self._pyaudio_instance = None

    def setup(self):
        segment = AudioSegment.from_wav(self.wav_filename)
        self._cough_volumes = Cougher._get_normalized_volume_samples(segment)

        self._cough_waveform = wave.open(self.wav_filename, 'rb')

        self._pyaudio_instance = pyaudio.PyAudio()

    def teardown(self):
        self._cough_waveform.close()
        self._cough_waveform = None

        self._pyaudio_instance.terminate()
        self._pyaudio_instance = None

    @classmethod
    def _get_normalized_volume_samples(cls, audio):
        dBs = [None] * len(audio)
        dBMin = 0
        for pos_ms in xrange(0, len(audio)):
            sample = audio[pos_ms]
            dBFS = sample.dBFS
            if isnan(dBFS) or isinf(dBFS):
                dBFS = 0

            if dBFS < dBMin:
                dBMin = dBFS

            dBs[pos_ms] = dBFS

        for i, val in enumerate(dBs):
            dBs[i] = max(0, min(1, 1.0 - abs(val / dBMin)))

        return dBs

    def _do_cough_lights(self):
        for i in xrange(0, len(self._cough_volumes), self.ms_stride_for_volume_samples):
            val = self._cough_volumes[i]
            # if val > 0.8: # just for drama
            #     val = 1.0

            if val < 0.2:
                val = 0.2

            h, s, v = self.color_hsv
            s = s - (s * val * self.whiteness_factor) # toward white

            for led_idx in range(8):
                distance_from_center = abs(round(led_idx - 3.5))
                pct_dfc = distance_from_center / 6.0

                Helpers.set_pixel_hsv(led_idx, (h, s, v), (1.0 - pct_dfc) * val * self.max_brightness_clamp)

            blinkt.show()
            sleep(self.ms_stride_for_volume_samples / 1000.0)

        blinkt.clear()
        blinkt.show()

    def cough(self):
        def audio_callback(in_data, frame_count, time_info, status_flags):
            return (self._cough_waveform.readframes(frame_count), pyaudio.paContinue)

        self._cough_waveform.rewind()

        try:
            stream = self._pyaudio_instance.open(
                        format=self._pyaudio_instance.get_format_from_width(self._cough_waveform.getsampwidth()),
                        channels=self._cough_waveform.getnchannels(),
                        rate=self._cough_waveform.getframerate(),
                        output=True,
                        stream_callback=audio_callback)

            self._do_cough_lights()

            stream.start_stream()

            while stream.is_active():
                sleep(0.1)
        finally:
            stream.stop_stream()
            stream.close()

if __name__ == '__main__':
    try:
        cough_hsv = (360.0, 1.0, 1.0)
        cough_filename = path.join(path.dirname(path.realpath(__file__)), '151217__owlstorm__cough-3.wav')
        cougher = Cougher(cough_filename, cough_hsv)
        cougher.setup()

        breathe_hsv = (161 / 360.0, 0.98, 1.0)
        breather = Breather(breathe_hsv)

        cougher.cough()
        sleep(1)
        cougher.cough()
        sleep(1)
        breather.breathe()
        sleep(1)
        breather.breathe()
    finally:
        if cougher is not None:
            cougher.teardown()
