import sys


from pathlib import Path
home = str(Path.home())

path = home+'/Platform/'

sys.path.insert (0, path)

from queue_req_resp import RabbitMQ
import xml.etree.ElementTree as ET
from threading import Thread
import requests
import json
import os
import subprocess
import signal
from Registry_API import *
from sched import *


################# DM Data Structures #################################
portBegin = 8501
serviceIDCommon = 4586 # a random number from which serviceID/AppID/ModelID will start

#MAP that will store serviceID : [pid1, pid2] so that thread can be deleted
servicePID = {} 

#MAP that will store hostIP : [occupied ports list]
hostOccupiedPorts = {} 

serviceInstanceCount = {}

################# DM Data Structures #################################

RMQ = RabbitMQ()

class ServiceManager():
	def __init__(self):
		# create a common queue on which all the modules will send request
		RMQ.create_queue("","modules_SM") 
		self.Registry = Registry_API()
		#thread that will monitor modules_SM Queue	
		t1 = Thread(target = self.SMInput, args = ('', "modules_SM",)) 
		t1.start()

	def getUsernamePassword(self, IP):
		# get username and password of this IP from registry
		# request to get data from registry on SM_RG queue
		# read RG_SM queue for the registry's response
		self.Registry.Read_Host_Creds([IP], "SM_RG", "RG_SM")
		creds = RMQ.receive_nonblock("", "RG_SM")
		'''
			Sample creds
			{
				"192.168.31.11": {
				"Username": "pranjali",
				"Password": "Accio@934"
				}
			}
		'''
		creds = json.loads(creds)
		print("Host Credentials:", creds)
		key = [k for k in creds.keys()]
		key = key[0]

		#assert to ensure that credentials are of the same IP we send a request for!
		try:
			assert(key == IP)

		except:
			print("IP is not matching with the credentials received from Registry")
			return None, None
		
		username = creds[IP]['Username']
		password = creds[IP]['Password']

		return username, password

	def SMInput(self, exchangeName, queueName):
		RMQ.receive(self.processSMInput, exchangeName, queueName)

	def processSMInput(self, ch, method, properties, body):
		data = json.loads(body)
		requestType = data['Request_Type']

		# increase serviceIDCommon by one at the end
		global serviceIDCommon
		# make entry of link : serviceIDCommon in the uniqueServiceID map
		global ServiceID
		global serviceInstanceCount
		global hostOccupiedPorts
		global servicePID

		if requestType == "Start_Model":
			'''
				{
					"Request_Type": "Start_Model",
					"Model_Link": [
						["192.168.31.12", "~/Platform/1/2/Models/Sonar", "456"],
						["192.168.31.13", "~/Platform/1/2/Models/Iris", "756"]
					]
				}
			'''
			# Start_Model is the request to start tensorflow serving for the model
			modelLinks = data['Model_Link']
			for model in modelLinks:
				IP = model[0]
				# link is the path where the model files are mounted
				link = model[1]
				link = link[1:]
				modelID = model[2] # unique id of the model
				inst = 0

				username, password = self.getUsernamePassword(IP)
				if username == None and password == None:
					return


				# username = "harshita"
				# password = "@14799741hA"

				if modelID not in serviceInstanceCount:
					serviceInstanceCount[modelID] = 1
					inst = 1
				else:
					serviceInstanceCount[modelID] += 1
					inst = serviceInstanceCount[modelID]

				rootLink = link #get the mount path of the service
				serviceName = link[link.rfind('/')+1:]
				for i in range(2):
					ind = rootLink.rfind('/')
					rootLink = rootLink[:ind]

				modelName = link[link.rfind('/')+1 : ]

				deployConfig = home+rootLink+'/Config/'+modelName+'_Model_DeployConfig.xml'
				prodConfig = home+rootLink+'/Config/'+modelName+'_Model_ProdConfig.xml'

				# home = '/home/'+username

				# Parsing Deployment Config
				tree = ET.parse(deployConfig)		
				root = tree.getroot()

				folderName = ""
				fileName = ""

				# get the folder name and file name of UI of Model
				for node in root.iter('UI'):
					for elements in node:
						if elements.tag == 'FolderPath':
							folderName = elements.text
						else:
							fileName = elements.text

				if fileName != "" and folderName != "":
					port = 0

					if IP not in hostOccupiedPorts:
						port = portBegin
						hostOccupiedPorts[IP] = []
					else:
						port = hostOccupiedPorts[IP][-1] + 1

					UILink = '/home/'+username+link+'/UI'

					#install flask module on the given host IP
					commandStr = "pip3 install flask; pip3 install flask_bcrypt; pip3 install pika; pip3 install xmlschema; pip3 install googleapiclient"
					osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
					print(osCommand)
					os.system(osCommand)
					print("Dependencies successfully installed on the host machine with IP:", IP)

					# Assumed: the name of executable will be run.py
					# navigate to the link and launch run.py

					commandStr = "python3 "+UILink+"/run.py  --port "+str(port)+" --service_id "+str(modelID)
					osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
					print(osCommand)
					pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
					print("UI for application ", link," started on IP:Port", IP,":",port)
					
					hostOccupiedPorts[IP].append(port)

					notifyFlask = {"Request_Type" : "Register_Service_UI"}
					notifyFlask['Service_ID'] = modelID
					notifyFlask["IP"] = IP
					notifyFlask["Port"] = port

					msg = json.dumps(notifyFlask)
					RMQ.send("","SM_Flask", msg)


				# for a model start tensorflow serving and launch its .py file
				# install tensorflow-model-server
				commandStr = "echo "+password+" sudo -S apt-get install tensorflow-model-server"
				osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
				print(osCommand)
				os.system(osCommand)
				print("tensorflow-model-server successfully installed on the host machine with IP:", IP)


				port = 0

				if IP not in hostOccupiedPorts:
					port = portBegin
					hostOccupiedPorts[IP] = []
				else:
					port = hostOccupiedPorts[IP][-1] + 1


				# start tensorflow model serving
				commandStr = "tensorflow_model_server --rest_api_port=" + str(port) + " --model_name=" + modelName + " --model_base_path=/home/" +username+modelLink 
				osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
				print(osCommand)
				pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
				print("tensorflow-model-server for service ", serviceName," started on IP:Port", IP,":",port)

				servicePID[serviceID].append(pro)
				pid = pro.pid

				self.Registry.Write_Service_Inst_Info(serviceID, [[IP, port, "Up", pid, 'model', serviceInst]], "SM_RG")

				hostOccupiedPorts[IP].append(port)

				# launch the model's repective py file
				commandStr = modelLink+'/ python3 '+modelName+".py  --serving_addrs "+IP+":"+str(port)+" --model /home/"+username+modelLink[2:]+" --service_id "+modelID
				if inst == 1:
					commandStr += " --is_first_instance yes"
				osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
				print(osCommand)
				pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
				print("Respective service file for the model started!")
				servicePID[serviceID].append(pro)

				pid = pro.pid

				self.Registry.Write_Service_Inst_Info(serviceID, [[IP, "", "Up", pid, 'exe', serviceInst]], "SM_RG")

				schedulerObj = PlatformScheduler()
				schedulerObj.schedule_service(modelID)


		elif requestType == "Start_App":
			'''
				{
					"Request_Type": "Start_App",
					"App_Link": [
						["192.168.31.12", "~/Platform/appDev/addID"]
					]
				}

				Dependency is to install flask module first
			'''
			# Start_App is the request to start flask application for an application/service
			App_links = data["App_Link"]
			for app in App_links:
				IP = app[0]
				link = app[1]
				link = link[1:]
				port = 0

				if IP not in hostOccupiedPorts:
					port = portBegin
					hostOccupiedPorts[IP] = []
				else:
					port = hostOccupiedPorts[IP][-1] + 1

				username, password = self.getUsernamePassword(IP)
				if username == None and password == None:
					return
				
				# home = '/home/'+username

				#install flask module on the given host IP
				commandStr = "pip3 install flask; pip3 install flask_bcrypt; pip3 install pika; pip3 install xmlschema; pip3 install googleapiclient"
				osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
				print(osCommand)
				os.system(osCommand)
				print("Dependencies successfully installed on the host machine with IP:", IP)

				# Assumed: the name of executable will be run.py
				# navigate to the link and launch run.py

				commandStr = "python3 /home/"+username+link+"/run.py "+str(port)
				osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
				print(osCommand)
				pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
				print("UI for application /home/",username, link," started on IP:Port", IP,":",port)
				
				hostOccupiedPorts[IP].append(port)

				notifyFlask = {"Request_Type" : "Register_Application_UI"}
				notifyFlask["App_Link"] = link
				notifyFlask["IP"] = IP
				notifyFlask["Port"] = port

				msg = json.dumps(notifyFlask)
				RMQ.send("","SM_Flask", msg)


		elif requestType == "Start_Service":
			'''
				{
					"Request_Type": "Start_Service",
					"Service_Link": [
						["192.168.31.12", "~/Platform/1/2/Services/Distance_Alarm_Service", "123"],
						["192.168.31.13", "~/Platform/1/2/Services/Helper_Service", "143"]
					]
				}
	
				All the services are .py files
				If starting a service for the first time
					python distance_alarm_service.py --service_id <dist_svc_1> --is_first_instance yes
				else
					python distance_alarm_service.py --service_id <dist_svc_1>
			'''
			Service_Links = data["Service_Link"]
			for service in Service_Links:
				IP = service[0]
				link = service[1]
				link = link[1:]
				print("Link:", link)
				serviceID = service[2] # unique id of the service

				if serviceID not in servicePID:
					servicePID[serviceID] = []

				if serviceID not in serviceInstanceCount:
					serviceInstanceCount[serviceID] = 1
				else:
					serviceInstanceCount[serviceID] += 1

				serviceInst = serviceInstanceCount[serviceID] 

				username, password = self.getUsernamePassword(IP)
				if username == None and password == None:
					return


				# username = "harshita"
				# password = "@14799741hA"

				rootLink = link #get the mount path of the service
				serviceName = link[link.rfind('/')+1:]
				for i in range(2):
					ind = rootLink.rfind('/')
					rootLink = rootLink[:ind]

				print("Rootlink:", rootLink)
				deployConfig = '/home/'+username+rootLink+'/Config/'+serviceName+'_DeployConfig.xml'
				prodConfig = '/home/'+username+rootLink+'/Config/'+serviceName+'_ProdConfig.xml'
				
				# home = '/home/'+username

				# Parsing Deployment Config
				tree = ET.parse(deployConfig)		
				root = tree.getroot()

				for dependency in root.iter('Dependencies'):
					for d in dependency:
						dependencyName = d.text
						print("dependency name: ", dependencyName)
						temp = dependencyName.split("_")
						if temp[-1] == 'Model':
							# the service is dependent on an AI Model
							modelName = dependencyName[:dependencyName.rfind('_')]
							modelLink = rootLink+'/Models/'+modelName

							print("Model Dependency of",modelName)

							# install tensorflow-model-server
							commandStr = "echo "+password+" sudo -S apt-get install tensorflow-model-server"
							osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
							print(osCommand)
							os.system(osCommand)
							print("tensorflow-model-server successfully installed on the host machine with IP:", IP)


							port = 0

							if IP not in hostOccupiedPorts:
								port = portBegin
								hostOccupiedPorts[IP] = []
							else:
								port = hostOccupiedPorts[IP][-1] + 1

							# start tensorflow model serving
							commandStr = "tensorflow_model_server --rest_api_port=" + str(port) + " --model_name=" + modelName + " --model_base_path=\"/home/" +username+modelLink+"\"" 
							osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
							print(osCommand)
							pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
							print("tensorflow-model-server for service ", serviceName," started on IP:Port", IP,":",port)

							servicePID[serviceID].append(pro)
							pid = pro.pid

							self.Registry.Write_Service_Inst_Info(serviceID, [[IP, port, "Up", pid, 'model', serviceInst]], "SM_RG")

							hostOccupiedPorts[IP].append(port)

							# launch the model's repective py file
							commandStr = '/home/'+username+modelLink+'/ python3 '+modelName+".py  --serving_addrs "+IP+":"+str(port)+" --model /home/"+username+modelLink+" --service_id "+serviceID
							if serviceInst == 1:
								commandStr += " --is_first_instance yes"
							osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
							print(osCommand)
							pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
							print("Respective service file for the model started!")
							servicePID[serviceID].append(pro)

							pid = pro.pid

							self.Registry.Write_Service_Inst_Info(serviceID, [[IP, "", "Up", pid, 'exe', serviceInst]], "SM_RG")


				for file in root.iter('ExecutableFileName'):
					if file.text == 'run.py':
						# this implies that the service has a related UI component
						port = 0

						if IP not in hostOccupiedPorts:
							port = portBegin
							hostOccupiedPorts[IP] = []
						else:
							port = hostOccupiedPorts[IP][-1] + 1

						UILink = '/home/'+username+link+'/UI'

						#install flask module on the given host IP
						commandStr = "pip3 install flask; pip3 install flask_bcrypt; pip3 install pika; pip3 install xmlschema"
						osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
						print(osCommand)
						os.system(osCommand)
						print("Dependencies successfully installed on the host machine with IP:", IP)

						# Assumed: the name of executable will be run.py
						# navigate to the link and launch run.py

						commandStr = "python3 "+UILink+"/run.py  --port "+str(port)+" --service_id "+str(serviceID)
						osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
						print(osCommand)
						pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
						print("UI for application ", UILink," started on IP:Port", IP,":",port)
						
						hostOccupiedPorts[IP].append(port)

						notifyFlask = {"Request_Type" : "Register_Service_UI"}
						notifyFlask['Service_ID'] = serviceID
						notifyFlask["IP"] = IP
						notifyFlask["Port"] = port

						msg = json.dumps(notifyFlask)
						RMQ.send("","SM_Flask", msg)


					elif file.text != None:
						# run normal .py services
						print("File Name: ", file.text)
						commandStr = "python3 /home/"+username+link+"/"+file.text+ " --service_id "+str(serviceID)
						
						if serviceInst == 1:
							commandStr += " --is_first_instance yes"

						osCommand = "sshpass -p \'" + password + "\' ssh -o StrictHostKeyChecking=no -t " + username + "@" + IP +" \'" +commandStr +"\'"
						print(osCommand)
						pro = subprocess.Popen(osCommand, stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
						print("Service /home/",username ,link," started on IP", IP)

						pid = pro.pid

						self.Registry.Write_Service_Inst_Info(serviceID, [[IP, "", "Up", pid, 'exe', serviceInst]], "SM_RG")

				schedulerObj = PlatformScheduler()
				schedulerObj.schedule_service(serviceID)

		elif requestType == "Kill":
			serviceID = data["Service_ID"]
			for p in servicePID[serviceID]:
				os.killpg(os.getpgid(p.pid), signal.SIGTERM)

if __name__ == '__main__':
	objSM = ServiceManager()


'''
Example Request:
{
"Request_Type": "Start_App",
"App_Link": [
             ["192.168.31.10", "/home/harshita/appDev/addID/tryUI"]
            ]
}


{
	"Request_Type": "Start_Model",
	"Model_Link": [
		["192.168.43.135", "~/1/1/Models/Sonar", "456"]
	]
}

{
"Request_Type" : "Kill",
"IP" : "some ip",
"PID" : 54512,
"Service_ID" : 452,
"Instance_ID" : 8
}

{
	"Request_Type": "Start_Service",
	"Service_Link": [
		["192.168.43.135", "~/1/1/Services/Counter_Service", "456"]
	]
}


'''