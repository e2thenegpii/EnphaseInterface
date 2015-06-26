import urllib.parse as p
import urllib.request as r
import datetime as dt
import dateutil.parser as dp
import json
import time
import logging

from lxml import etree as et

import EnphaseInterface as ei

def parseEnergy(data):
    for k,v in data.items():
        if v[-3:] == 'MWh' or v[-2:] == 'MW':
            data[k] = int(float(v.split()[0])*(10**6))
        elif v[-3:] == 'kWh' or v[-2:] == 'kW':
            data[k] = int(float(v.split()[0])*(10**3))
        elif v[-2:] == 'Wh' or v[-1:] == 'W':
            data[k] = int(float(v.split()[0])*(10**0))
    return data

class EnvoyInterface(object):
    def __init__(self, envoyUrl,
        wrapper=ei.EnphaseOutputWrapperRaw()):
        
        self.envoyUrl = envoyUrl
        self.dtt = ei.DateTimeType.Enphase
        self.opener = r.build_opener()
        self.wrapper = wrapper
        
    def _getPage(self,action,**kwargs):
    
        query = p.urlencode(kwargs)
        
        request = p.urlunsplit(('http',self.envoyUrl,action,query,''))
        
        logging.debug(request)
        response = self.opener.open(request)
        
        logging.debug(response.geturl())
        
        return et.HTML(response.read().decode(encoding='UTF-8'))
        
    def _parseProduction(self):
        
        root = self._getPage('production', locale='en')
        table = root.find('.//div[@style]/table')
        data = {}
        for row in table.findall('./tr'):
            if len(row) > 1:
                key,value = row
                data[key.text] = value.text.strip()
            else:
                data['start_date'] = row.find('.//div[@class="good"]').text.strip()
        
        return parseEnergy(data)
        
    def _parseHome(self):

        data = {}    
        root = self._getPage('home', locale='en')
        
        serial = root.xpath('.//td[contains(text(),"Envoy Serial Number")]')
        
        key,value = serial[0].text.split(':',1)
        data[key] = value.strip()
        
        table = root.findall('.//table[@style]')[1]

        for div in table.findall('.//div[@class]'):
            if div.text is not None:
                if div.text.strip() == 'Connection to Web':
                    if div.attrib['class'] == 'good':
                        data['status'] = 'normal'

        if 'status' not in data:
            data['status'] = 'comm'
            
        table2 = table.find('.//table')
        
        for k,v in table2.findall('.//tr'):
            if v.text is None:
                data[k.text] = v[0].text.strip()
            else:
                data[k.text] = v.text.strip()

        return parseEnergy(data)
        
    def _parseInventory(self):
        root = self._getPage('inventory',locale='en')
        

    def energy_lifetime(self, system_id, **kwargs):
        '''Get the lifetime energy produced by the system
            Unlike the Enphase Restful interface this can only
            return the total from the original date and is returned
            as a single value, any start_date and end_date are ignored'''
            
        data = self._parseProduction()
        
        j = {}
        
        j['start_date'] = data['start_date']
        j['system_id'] = int(system_id)
        j['production'] = [data['Since Installation']]
        
        return json.dumps(j)

    def envoys(self, system_id, **kwargs):
        '''List the envoys associated with the system
            Unlike the Enphase Restful interface this can only
            return data for the envoy we're querying'''
            
        j = {}

        data = self._parseHome()
        j['system_id'] = int(system_id)
        envoy = {}
        
        delta = dt.timedelta(minutes=int(data['Last connection to website'].split()[0]))
        envoy['envoy_id'] = 0
        envoy['last_report_at'] = int((delta + dt.datetime.now()).timestamp())
        envoy['name'] = 'Envoy %s' % data['Envoy Serial Number']
        envoy['part_number'] = ''
        envoy['serial_number'] = data['Envoy Serial Number']
        envoy['status'] = data['status']
        
        j['envoys'] = [envoy]
        
        return json.dumps(j)

    
    def index(self, **kwargs):
        '''List the systems available by this API key'''

        raise NotImplementedError()
        
    def inventory(self, system_id, **kwargs):
        '''List the inverters associated with this system'''
        
        j = {}
        action = 'datatab/inventory_dt.rb'
        query = p.urlencode({'locale':'en','name':'PCU'})
        
        request = p.urlunsplit(('http',self.envoyUrl,action,query,''))
        
        response = self.opener.open(request)
        
        data = json.loads(response.read().decode(encoding='UTF-8'))
        
        j['system_id'] = int(system_id)
        inverters = []
        for d in data['aaData']:
            inverters.append({'sn':d[2],'model':'unknown'})
        j['inverters'] = inverters

        return json.dumps(j)

    def monthly_production(self, system_id, start_date, **kwargs):
        '''List the energy produced in the last month'''

        raise NotImplementedError()

    def rgm_stats(self, system_id, **kwargs):
        '''List the Revenue Grade Meter stats'''

        raise NotImplementedError()

    def stats(self, system_id, **kwargs):
        '''Get the 5 minute interval data for the given day
            This function ignores the start at or end at parameters'''

        j = {}
        data = self._parseHome()
        powr = data['Currently generating']
        enwh = int(float(powr)/12)
        ts = dt.datetime.now()
        ts = ts.replace(microsecond=0,second=0,minute=int((ts.minute/5)*5))
        ts = int(ts.timestamp())
        micros = int(data['Number of Microinverters'])
        reading = {'end_at':ts,'powr':powr,'enwh':enwh,'devices_reporting':micros}
        j['system_id'] = int(system_id)
        j['total_devices'] = int(data['Number of Microinverters'])
        j['intervals'] = [reading]

        return json.dumps(j)

    def summary(self, system_id, **kwargs):
        '''Get the system summary'''

        return self._execQuery(system_id, 'summary', kwargs)
