#!/usr/bin/env python3
"""
Very simple HTTP server in python for logging requests
Usage::
    ./server.py [<port>]
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import json
from pprint import pprint
from hpeOneView.oneview_client import OneViewClient
import sys, os
import base64

class S(BaseHTTPRequestHandler):
    oneviewClient = None
    used = False
    
    def _set_response(self, ct):
        self.send_response(200)
        self.send_header('Content-type', ct)
        self.end_headers()

    def do_GET(self):
        if self.path == "/bmhs.js":
            self._set_response('text/javascript')
            js = "var bmhs = "+json.dumps(bmhs())
            self.wfile.write(js.encode('utf-8'))
        elif self.path == "/index.html" or self.path == "/":
            file = open("resources/index.html")
            self._set_response('text/html')
            self.wfile.write(file.read().encode('utf-8'))
        elif self.path == "/index.css":
            file = open("resources/index.css")
            self._set_response('text/css')
            self.wfile.write(file.read().encode('utf-8'))
        else:
            self._set_response('text/html')
            self.wfile.write("GET request for {}".format(self.path).encode('utf-8'))

    def do_POST(self):
        if self.path == "/index.html" or self.path == "/":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params=post_data.split("&")
            serverName = ""
            templateName = "Openshift-BM"
            for param in params:
                arr = param.split("=")
                if arr[0]=="bmh" and len(arr)>1:
                    serverName = arr[1]
                if arr[0]=="template" and len(arr)>1:
                    templateName = arr[1]
            createBmh(serverName, templateName)
            file = open("resources/index.html")
            self._set_response('text/html')
            self.wfile.write(file.read().encode('utf-8'))
        else:
            content_length = int(self.headers['Content-Length']) # <--- Gets the size of data
            post_data = self.rfile.read(content_length) # <--- Gets the data itself
            self._set_response('text/html')
            self.wfile.write("POST request for {}".format(self.path).encode('utf-8'))

def run(server_class=HTTPServer, handler_class=S, port=80):
    logging.basicConfig(level=logging.INFO)
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    logging.info('Starting httpd...\n')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info('Stopping httpd...\n')

def bmhs():
  bmhs = {}
  if S.used: return bmhs
  S.used = True
  file=open('resources/bmh.yaml')
  yaml = file.read()
  file.close()
  oneview_client = oneviewClient()
  try:
    server_profiles = oneview_client.server_profiles
    server_hardwares = oneview_client.server_hardware
    server_hardware_all = server_hardwares.get_all()
    all_profiles = server_profiles.get_all()
    profile_templates = oneview_client.server_profile_templates
    all_templates = profile_templates.get_all()    
    
    templatesUri = {}
    for template in all_templates:
      templatesUri[template['uri']] = template['name']
    
    for profile in all_profiles:
      role = ''
      if 'master' in profile['name']: role = 'master'
      if 'worker' in profile['name']: role = 'worker'
      bmh = {'role':role, 'username':os.environ.get('ONEVIEWSDK_USERNAME', ''),'password':os.environ.get('ONEVIEWSDK_PASSWORD', '')}
      if profile['serverProfileTemplateUri'] is not None and templatesUri[profile['serverProfileTemplateUri']]:
        bmh['template']=templatesUri[profile['serverProfileTemplateUri']];
      for conn in profile['connectionSettings']['connections']:
        if conn['name'] == "RedHat_MGMT":
          bmh['mac']=conn['mac']
        if conn['name'] == "RedHat_WRKLD":
          bmh['mac-baremetal']=conn['mac']        
      for hard in server_hardware_all:
        if hard['uri'] == profile['serverHardwareUri'] and hard['maintenanceMode'] == False:
          bmh['url']='ipmi://'+hard['mpHostInfo']['mpIpAddresses'][0]['address']
          bmh['power'] = hard['powerState']
      cluster = None
      try:
          file=open("bmhs/"+profile['name']+".cluster")
          bmh['cluster']=file.read()
          file.close()
      except Exception as ee:
          pass
      if 'power' in bmh and 'url' in bmh and 'mac' in bmh and 'role' in bmh:
        if 'cluster' not in bmh and bmh['power'] == 'Off':
          file=open('bmhs/'+profile['name']+'.yaml', 'w+')
          str=yaml.replace('@name@', profile['name'])
          for key in ['url', 'mac', 'role']:
            str = str.replace('@'+key+'@', bmh[key])
          str=str.replace('@username64@', b64(bmh['username']))
          str=str.replace('@password64@', b64(bmh['password']))
          file.write(str)
          file.close()
          file=open('bmhs/'+profile['name']+'.mac', 'w+')
          file.write(bmh['mac-baremetal'])
          file.close()
        bmhs[profile['name']]=bmh
  except Exception as e:
    pprint(e)
  #pprint(bmhs)
  S.used = False
  return bmhs

def b64(message):
  message_bytes = message.encode('ascii')
  base64_bytes = base64.b64encode(message_bytes)
  return base64_bytes.decode('ascii')        

def getServerProfileTemplates(all_templates, templateName):
  templates = {}
  for template in all_templates:
    if template['name'] == templateName or template['name'].startswith(templateName+'-'):
        templates[template['serverHardwareTypeUri']]=template['uri']
  return templates

def createBmh(serverName, templateName):
  oneview_client = OneViewClient.from_environment_variables()
  server_profiles = oneview_client.server_profiles
  all_profiles = server_profiles.get_all()
  server_hardwares = oneview_client.server_hardware
  server_hardware_all = server_hardwares.get_all()
  profile_templates = oneview_client.server_profile_templates
  all_templates = profile_templates.get_all()
  templates = getServerProfileTemplates(all_templates, templateName)

  if serverName != '':
    for prof in all_profiles:
      if prof['name'] == serverName:
        return False
    
  servers = []
  for serv in server_hardware_all:
    if serv['serverProfileUri'] is None and \
       serv['powerState'] == 'Off' and \
       serv['maintenanceMode'] == False and \
       serv['model'] == 'ProLiant BL460c Gen9' and \
       serv['state'] == 'NoProfileApplied' and \
       serv['status'] != 'Critical' and \
       templates[serv['serverHarwareTypeUri']] is not None:
      servers.append(serv)

  if len(servers) == 0: return False
  server = servers[-1];
  serv_template = templates[server['serverHarwareTypeUri']]
  if serverName == '': serverName = 'node-'+server['serialNumber'].lower();
  ls =  {'controllers': [{'deviceSlot': 'Embedded',
                                   'driveWriteCache': 'Unmanaged',
                                   'importConfiguration': False,
                                   'initialize': True,
                                   'logicalDrives': [],
                                   'mode': 'HBA',
                                   'predictiveSpareRebuild': 'Unmanaged'}],
                  'reapplyState': 'NotApplying',
                  'sasLogicalJBODs': []}
  options = dict(
      name=serverName,
      serverHardwareUri=server['uri'],
      serverProfileTemplateUri=serv_template['uri'],
      localStorage=ls
  )
  profile = oneview_client.server_profiles.create(options, force=True)

  options = dict(serverProfileTemplateUri=serv_template['uri'])
  profile.patch(operation="replace", path="/templateCompliance", value="Compliant")
  return True

def oneviewClient():
  if S.oneviewClient is None:
    try:
      S.oneviewClient = OneViewClient.from_environment_variables()
    except Exception:
      sys.exit(1)
  return S.oneviewClient

if __name__ == '__main__':
    from sys import argv

    if len(argv) == 2:
        run(port=int(argv[1]))
    else:
        run()
