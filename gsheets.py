# 2018 / MIT / Tim Clem / github.com/misterfifths
# See LICENSE for details

from __future__ import print_function

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from time import sleep
from os import path
from sys import stderr

class GoogleSheetsLogger(object):
    def __init__(self, sheet_key):
        self.sheet_key = sheet_key

        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']

        creds_file = path.join(path.dirname(path.realpath(__file__)), 'gsheets-creds.json')
        self._credentials = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)

        self._worksheet = None

    def setup(self):
        gs = gspread.authorize(self._credentials)

        spreadsheet = gs.open_by_key(self.sheet_key)

        self._worksheet = spreadsheet.get_worksheet(0)

    def log(self, air_quality):
        try:
            self._worksheet.append_row((air_quality.timestamp.isoformat(sep=' '), air_quality.co2_ppm, air_quality.voc_ppb))
            print('[logged]', file=stderr)
        except:
            print('[logging error]', file=stderr)
