from sensor import *
import time
import datetime
import numpy as np
import pandas as pd
import sys
from timer import *

class SonarSensor(Sensor):
    def __init__(self, rate = 10, dest_IP = "127.0.0.1", dest_port = 4444):
        description = "This is a Naval mine sensor taking in Sonar Data."
        self.name = "SONAR_SENSOR"
        Sensor.__init__(self, description, "one-way", rate, dest_IP, dest_port)

        self.dataset = pd.read_csv("./Sonar.csv").values
        self.length = self.dataset.shape[0]
        self.index = 0

    # sends simulated input to the Sensor Manager, in the prescribed rate
    # using sockets
    def send_simulated_input(self):
        sonar_data = self.name + f"${self.dataset[self.index][:-1]}"
        self.index = (self.index + 1) % self.length

        self.send_data(sonar_data)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print ("Usage: sonar_sensor.py <sensor_manager_IP> <sensor_manager_port>")
        sys.exit(1)

    sonar_sensor = SonarSensor(dest_IP = sys.argv[1], dest_port = sys.argv[2])
    sensor_data_timer = RepeatedTimer(sonar_sensor.rate, sonar_sensor.send_simulated_input)
    sensor_data_timer.start()
