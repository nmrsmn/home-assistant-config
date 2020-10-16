# Imports
import logging
from datetime import date, datetime, timedelta

import re
import json
import requests

import homeassistant.helpers.config_validation as validation
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

# Logging
logger = logging.getLogger(__name__)

# Constants
DOMAIN = 'garbage'
ICON = 'mdi:delete-empty'
DEFAULT_NAME = 'garbage'

CONST_POSTAL = 'postal'
CONST_HOUSENUMBER = 'housenumber'
CONST_ADDITION = 'addition'

CONST_LABELS = 'labels'
CONST_LABEL_NOTHING = 'nothing'
CONST_LABEL_SEPARATOR = 'separator'

CONST_LABEL_NOTHING_DEFAULT = 'None'
CONST_LABEL_SEPARATOR_DEFAULT = 'and'

SCAN_INTERVAL = timedelta(seconds=30)
UPDATE_EVERY = timedelta(seconds=3600)

CONST_JSON_URL = "https://api.mijnafvalwijzer.nl/webservices/appsinput/?apikey=5ef443e778f41c4f75c69459eea6e6ae0c2d92de729aa0fc61653815fbd6a8ca&method=postcodecheck&postcode={0}&street=&huisnummer={1}&toevoeging={2}&platform=phone&langs=nl"

# Configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): validation.string,
    vol.Required(CONST_POSTAL): validation.string,
    vol.Required(CONST_HOUSENUMBER): validation.string,
    vol.Optional(CONST_ADDITION, default=""): validation.string,
    vol.Optional(CONST_LABELS): {
        vol.Optional(CONST_LABEL_NOTHING, default=CONST_LABEL_NOTHING_DEFAULT): validation.string,
        vol.Optional(CONST_LABEL_SEPARATOR, default=CONST_LABEL_SEPARATOR_DEFAULT): validation.string
    }
})

# Setup the platform
async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    try:
        garbage_service = GarbageService(config)
    except ValueError as error:
        logger.error("Check GarbageService platform settings: %s", error)
        raise
        
    garbage_types = ['today', 'tomorrow']
    for item in garbage_service.garbage_types_list:
        garbage_types.append(item)
    
    schedule_service = (GarbageScheduleService(config))

    sensors = []
    for name in garbage_types:
        sensors.append(GarbageSensor(hass, name, schedule_service, config))

    async_add_entities(sensors)

# Sensor class
class GarbageSensor(Entity):
    def __init__(self, hass, name, schedule_service, config):
        self._hass = hass
        self._name = name
        self._schedule_service = schedule_service
        self._config = config
        
        self._attributes = {}
        self._state = config.get(CONST_LABELS).get(CONST_LABEL_NOTHING)
        
    @property
    def name(self):
        return self._config.get(CONF_NAME) + "_" + self._name
        
    @property
    def state(self):
        return self._state

    @property
    def icon(self):
        return ICON
        
    @property
    def device_state_attributes(self):
        return self._attributes
    
    async def async_update(self):
        self._schedule_service.update()
        self._state = self._config.get(CONST_LABELS).get(CONST_LABEL_NOTHING)
        
        for item in self._schedule_service.garbage_schedule_default:
            if self._name not in ['today', 'tomorrow']:
                attributes = {}
                attributes['days'] = item['remaining']
                if item['key'] == self._name:
                    self._state = item['value']
                    self._attributes = attributes
            
        for item in self._schedule_service.garbage_schedule_additional:
            if item['key'] == self._name:
                if item['value'] != self._config.get(CONST_LABELS).get(CONST_LABEL_NOTHING):
                    self._state = item['value']

# Schedule service class
class GarbageScheduleService(object):
    def __init__(self, config):
        self._config = config

    @Throttle(UPDATE_EVERY)
    def update(self):
        try:
            garbage_service = GarbageService(self._config)
        except ValueError as error:
            logger.error("Check GarbageService platform settings: %s", error)
            raise
            
        try:
            self.garbage_schedule_default = garbage_service.garbage_schedule_full_json
        except ValueError as error:
            logger.error("Check garbage_schedule_default %s", error.args)
            self.garbage_schedule_default = self._config(CONST_LABELS).get(CONST_LABEL_NOTHING)
                
        try:
            self.garbage_schedule_additional = garbage_service.garbage_schedule_today_json + garbage_service.garbage_schedule_tomorrow_json
        except ValueError as error:
            logger.error("Check garbage_schedule_additional %s", error.args)
            self.garbage_schedule_additional = self._config(CONST_LABELS).get(CONST_LABEL_NOTHING)
            
# Garbage service class
class GarbageService(object):
    def __init__(self, config):
        self._config = config
    
        self._housenumber = self._config.get(CONST_HOUSENUMBER)
        self._addition = self._config.get(CONST_ADDITION)
        
        postal = re.match('^\d{4}[a-zA-Z]{2}', self._config.get(CONST_POSTAL))
        if postal:
            self._postal = postal.group()
        else:
            raise ValueError("Incorrect postal code format. Was {}, but AAAA11 expected".format(postal))
            
        self._today = datetime.today().strftime('%Y-%m-%d')
        self._tomorrow = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        self._data = self.get_json_data()
        self._types = self.get_garbage_types()
        self._garbage_schedule_full, self._garbage_schedule_today, self._garbage_schedule_tomorrow = self.get_garbage_schedule()
        
    def get_json_data(self):
        url = CONST_JSON_URL.format(self._postal, self._housenumber, self._addition)
        response = requests.get(url).json()
        return (response['data']['ophaaldagen']['data'] + response['data']['ophaaldagenNext']['data'])
        
    def get_garbage_types(self):
        garbage_types = []
        for item in self._data:
            garbage = item['nameType']
            if garbage not in garbage_types:
                garbage_types.append(garbage)
        return garbage_types
        
    def get_garbage_schedule(self):
        garbage_type = {}
        garbage_today = {}
        garbage_tomorrow = {}
        
        multi_garbage_today = []
        multi_garbage_tomorrow = []
        
        garbage_schedule_full = []
        garbage_schedule_today = []
        garbage_schedule_tomorrow = []
        
        garbage_types = ['today', 'tomorrow']
        garbage_types.extend(self._types)
        
        nothing = self._config.get(CONST_LABELS).get(CONST_LABEL_NOTHING)
        separator = self._config.get(CONST_LABELS).get(CONST_LABEL_SEPARATOR)
        
        # Some date count functions for next
        def d(s):
            [year, month, day] = map(int, s.split('-'))
            return date(year, month, day)

        def days(start, end):
            return (d(end) - d(start)).days
            
        for name in garbage_types:
            for item in self._data:
                name = item['nameType']
                converted = datetime.strptime(item['date'], '%Y-%m-%d').strftime('%d-%m-%Y')
                        
                if name not in garbage_type:
                    display_name = name.capitalize()
                    if name == 'gft':
                        display_name = 'GFT'
                    
                    if item['date'] >= self._today:
                        garbage_type[name] = name
                        
                        garbage = {}
                        garbage['key'] = name
                        garbage['value'] = converted
                        garbage['remaining'] = (days(self._today, item['date']))
                        
                        garbage_schedule_full.append(garbage)
                        
                    if item['date'] == self._today:
                        garbage_type['today'] = "today"
                        garbage_today['key'] = "today"
                        
                        if len(multi_garbage_today) == 0:
                            garbage_today['value'] = display_name
                        else:
                            garbage_today['value'] = ', '.join(multi_garbage_today) + ' ' + separator + ' ' + display_name
                        
                        multi_garbage_today.append(display_name)
                        garbage_schedule_today.append(garbage_today)

                    if item['date'] == self._tomorrow:
                        garbage_type['tomorrow'] = "tomorrow"
                        garbage_tomorrow['key'] = "tomorrow"
                        
                        if len(multi_garbage_tomorrow) == 0:
                            garbage_tomorrow['value'] = display_name
                        else:
                            garbage_tomorrow['value'] = ', '.join(multi_garbage_tomorrow) + ' ' + separator + ' ' + display_name
                        
                        multi_garbage_tomorrow.append(display_name)
                        garbage_schedule_tomorrow.append(garbage_tomorrow)
                        
            if len(garbage_schedule_today) == 0:
                garbage_type[name] = "today"
                garbage_today['key'] = "today"
                garbage_today['value'] = nothing
                garbage_schedule_today.append(garbage_today)

            if len(garbage_schedule_tomorrow) == 0:
                garbage_type[name] = "tomorrow"
                garbage_tomorrow['key'] = "tomorrow"
                garbage_tomorrow['value'] = nothing
                garbage_schedule_tomorrow.append(garbage_tomorrow)
                 
        return garbage_schedule_full, garbage_schedule_today, garbage_schedule_tomorrow
    
    @property
    def garbage_schedule_full_json(self):
        return self._garbage_schedule_full
    
    @property
    def garbage_schedule_today_json(self):
        return self._garbage_schedule_today

    @property
    def garbage_schedule_tomorrow_json(self):
        return self._garbage_schedule_tomorrow
        
    @property
    def garbage_types_list(self):
        return self._types
