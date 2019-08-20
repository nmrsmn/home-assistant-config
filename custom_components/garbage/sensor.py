# Imports
import logging
from datetime import date, datetime, timedelta

import requests

import homeassistant.helpers.config_validation as validation
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

# General
logger = logging.getLogger(__name__)

# Constants
DOMAIN = 'garbage'
ICON = 'mdi:delete-empty'
DEFAULT_NAME = 'garbage'

CONST_POSTAL = 'postal'
CONST_HOUSENUMBER = 'housenumber'
CONST_ADDITION = 'addition'

SCAN_INTERVAL = timedelta(seconds=30)
UPDATE_EVERY = timedelta(seconds=3600)

CONST_JSON_URL = "https://json.mijnafvalwijzer.nl/?method=postcodecheck&postcode={0}&street=&huisnummer={1}&toevoeging={2}&platform=phone&langs=nl&"
CONST_SCRAPPER_URL = ""

# Configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): validation.string,
    vol.Required(CONST_POSTAL): validation.string,
    vol.Required(CONST_HOUSENUMBER): validation.string,
    vol.Optional(CONST_ADDITION, default=""): validation.string
})

# Setup the platform
def setup_platform(hass, config, add_entities, discovery_info=None):
    
    postal = config.get(CONST_POSTAL)
    housenumber = config.get(CONST_HOUSENUMBER)
    addition = config.get(CONST_ADDITION)

    if None in (postal, housenumber):
        logger.error("Postal and/or housenumber aren't set in the config!")

    response = requests.get(CONST_JSON_URL.format(postal, housenumber, addition))
    if response.status_code != requests.codes.ok:
        logger.exception("Error doing API request")
    
    json = response.json()
    data = (json['data']['ophaaldagen']['data'] + json['data']['ophaaldagenNext']['data'])

    thrashes = []
    moments = ['today', 'tomorrow', 'next']
    thrashes.extend(moments)

    for item in data:
        if item["nameType"] not in thrashes:
            thrashes.append(item["nameType"])

    data = (GarbageSchedule(thrashes, config))

    sensors = []
    for name in thrashes:
        sensors.append(GarbageSensor(name, data, config))

    add_entities(sensors)

# Sensor class
class GarbageSensor(Entity):
    def __init__(self, name, data, config):
        self._name = name
        self._state = "Geen"
        self.config = config
        self.data = data

    @property
    def name(self):
        return self.config.get(CONF_NAME) + "_" + self._name
        
    @property
    def state(self):
        return self._state

    @property
    def icon(self):
        return ICON

    def update(self):
        self.data.update()
        self._state = "Geen"

        for item in self.data.data:
            if item['key'] == self._name:
                self._state = item['value']

# Schedule class
class GarbageSchedule(object):
    def __init__(self, thrashes, config):
        self._thrashes = thrashes
        self.config = config
        self.data = None

    @Throttle(UPDATE_EVERY)
    def update(self):
        postal = self.config.get(CONST_POSTAL)
        housenumber = self.config.get(CONST_HOUSENUMBER)
        addition = self.config.get(CONST_ADDITION)

        response = requests.get(CONST_JSON_URL.format(postal, housenumber, addition))

        json = response.json()
        data = (json['data']['ophaaldagen']['data'] + json['data']['ophaaldagenNext']['data'])

        today = datetime.today().strftime('%Y-%m-%d')
        tomorrow = datetime.strftime(datetime.today() + timedelta(days=1), '%Y-%m-%d')

        types = {}
        trashNext = {}
        trashToday = {}
        trashTodayTypes = []
        trashTomorrow = {}
        trashTomorrowTypes = []
        schedule = []

        # Some date count functions for next
        def d(s):
            [year, month, day] = map(int, s.split('-'))
            return date(year, month, day)

        def days(start, end):
            return (d(end) - d(start)).days

        # Loop through all thrashtypes
        for name in self._thrashes:
            for item in data:
                if item['nameType'] not in types:

                    # Add every item not yet passed to the schedule
                    if item['date'] >= today:
                        trash = {}
                        trash['key'] = item['nameType']
                        trash['value'] = datetime.strptime(item['date'], '%Y-%m-%d').strftime('%d-%m-%Y')
                        
                        schedule.append(trash)
                        types[item['nameType']] = item['nameType']

                    # Add the number of days untill the next garbage collection day as next
                    if item['date'] > today:
                        if len(trashNext) == 0:
                            trashNext['key'] = "next"
                            trashNext['value'] = (days(today, item['date']))

                            schedule.append(trashNext)
                            types[item['nameType']] = "next"

                    formattedName = item['nameType']
                    if formattedName == "gft":
                        formattedName = "GFT"
                    elif formattedName == "pmd":
                        formattedName = "Plastic"
                    else: 
                        formattedName = formattedName.capitalize()

                    if item['date'] == today:
                        trashToday['key'] = "today"

                        if len(trashTodayTypes) == 0:
                            trashToday['value'] = formattedName
                        else:
                            trashToday['value'] = ', '.join(trashTodayTypes) + ' en ' + formattedName

                        trashTodayTypes.append(formattedName)

                        schedule.append(trashToday)
                        types[item['nameType']] = "today"
                        
                    if item['date'] == tomorrow:
                        trashTomorrow['key'] = "tomorrow"
                        
                        if len(trashTomorrowTypes) == 0:
                            trashTomorrow['value'] = formattedName
                        else:
                            trashTomorrow['value'] = ', '.join(trashTomorrowTypes) + ' en ' + formattedName

                        trashTomorrowTypes.append(formattedName)

                        schedule.append(trashTomorrow)
                        types[item['nameType']] = "tomorrow"
                        
        self.data = schedule
