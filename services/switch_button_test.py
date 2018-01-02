#!/usr/bin/python3

import sys, os

import time
import datetime
import picamera
import picamera.array
import numpy as np
import serial
import argparse
import RPi.GPIO as GPIO  

# for call USB stick functions
# import ottoUSBdriveFunctions as USBfunct

# -------- New Power On/Off functionality --------- 

# 1- User holds boot switch in ON position which energizes power relay coil ( power LED remains unlit )
# 2- Relay contacts close supplying 5 volts to Pi.
# 3- Pi boots, executes service program which also energizes relay coil
# 4- Pi turns on power LED to indicate to user that the Pi is under control
# 5- User releases toggle switch, but Pi has already latched relay contacts closed so it remains powered
# 6- Program continues to execute until user flips power off switch telling Pi to shut it down

#	CONSTANTS are in ALL CAPS

# -------- GPIO pin numbers for ottoMicro Car --------- 
LED_read_from_USBdrive = 2
LED_save_to_USBdrive = 3
LED_collect_data = 4
LED_autonomous = 17
LED_shutdown_RPi = 27
LED_boot_RPi = 22

SWITCH_collect_data = 10
SWITCH_save_to_USBdrive = 9
SWITCH_read_from_USBdrive = 11
SWITCH_run_autonomous = 5
SWITCH_shutdown_RPi = 6
# SWITCH_boot_RPi = relay coil

OUTPUT_to_relay = 13

# -------- Button or switch (switchs) constants --------- 
# switch push or switch position-up connects to ground, 
#  thus internal pull up  resistors are used  
ON = GPIO.LOW		# LOW signal on GPIO pin means switch is ON (up position)		
OFF = GPIO.HIGH		# HIGH signal on GPIO pin means switch is OFF (down position)
PUSHED = GPIO.LOW	# LOW signal on GPIO pin means switch is PUSHED
UP = GPIO.HIGH		# HIGH signal on GPIO pin means switch is UP

# -------- LED state constants --------- 
LED_ON = GPIO.HIGH
LED_OFF = GPIO.LOW

# -------- Kind of error constants --------- 
NONE = 0
WARNING = 1
FATAL = 2
NO_USB_DRIVE_WARNING = 3
AUTONOMOUS_WARNING = 4
RECORDED_DATA_NOT_SAVED = 5

# --------Old Data Collection Command Line Startup Code--------- 
time_format='%Y-%m-%d_%H-%M-%S'

#	**** fubarino not hooked up for debugging purposes ****
#Opens serial port to the arduino:
#try:
#	ser=serial.Serial('/dev/ttyACM0')
#except serial.SerialException:
#	print('Cannot connect to serial port')
 
# -------------- Data Collector Object -------------------------------  

NUM_FRAMES = 100

class DataCollector(object):
	'''this object is passed to the camera.start_recording function, which will treat it as a 
	writable object, like a stream or a file'''
	def __init__(self):
		self.imgs=np.zeros((NUM_FRAMES, 64, 64, 3), dtype=np.uint8) #we put the images in here
		self.IMUdata=np.zeros((NUM_FRAMES, 7), dtype=np.float32) #we put the imu data in here
		self.RCcommands=np.zeros((NUM_FRAMES, 2), dtype=np.float16) #we put the RC data in here
		self.idx=0 # this is the variable to keep track of number of frames per datafile
		nowtime=datetime.datetime.now()
		self.img_file='/home/pi/autonomous/data/imgs_{0}'.format(nowtime.strftime(time_format))
		self.IMUdata_file='/home/pi/autonomous/data/IMU_{0}'.format(nowtime.strftime(time_format))
		self.RCcommands_file='/home/pi/autonomous/data/commands_{0}'.format(nowtime.strftime(time_format))

	def write(self, s):
		'''this is the function that is called every time the PiCamera has a new frame'''
		imdata=np.reshape(np.fromstring(s, dtype=np.uint8), (64, 64, 3), 'C')
		#now we read from the serial port and format and save the data:
		try:
			ser.flushInput()
			datainput=ser.readline()
			data=list(map(float,str(datainput,'ascii').split(','))) #formats line of data into array
			print(data)
			print("got cereal\n")

		except:
			print(err)
			print( "exception in data collection write" )
			return 
			
		#Note: the data from the IMU requires some processing which does not happen here:
		self.imgs[self.idx]=imdata
		accelData=np.array([data[0], data[1], data[2]], dtype=np.float32)
		gyroData=np.array([data[3], data[4], data[5]], )
		datatime=np.array([int(data[6])], dtype=np.float32)
		steer_command=int(data[7])
		gas_command=int(data[8])
		self.IMUdata[self.idx]=np.concatenate((accelData, gyroData, datatime))
		self.RCcommands[self.idx]=np.array([steer_command, gas_command])
		self.idx+=1
		if self.idx == NUM_FRAMES: #default value is 100, unless user specifies otherwise
			self.idx=0
			self.flush()  

	def flush(self):
		'''this function is called every time the PiCamera stops recording'''
		np.savez(self.img_file, self.imgs)
		np.savez(self.IMUdata_file, self.IMUdata)
		np.savez(self.RCcommands_file, self.RCcommands)
		#this new image file name is for the next chunk of data, which starts recording now
		nowtime=datetime.datetime.now()
		self.img_file='/home/pi/autonomous/data/imgs_{0}'.format(nowtime.strftime(time_format))
		self.IMUdata_file='/home/pi/autonomous/data/IMU_{0}'.format(nowtime.strftime(time_format))
		self.RCcommands_file='/home/pi/autonomous/data/commands_{0}'.format(nowtime.strftime(time_format))
		self.imgs[:]=0
		self.IMUdata[:]=0
		self.RCcommands[:]=0

# -------- Switch / Button use cheatsheet --------- 
#
# Switch / Button		STATE		MEANING
# --------------------------------------------------------------
# SWITCH_boot_RPi		momentary up	Boot up RPi		
#				down		normal RPi operation
#
# SWITCH_shutdown_RPi		momentary up	Gracefully shutdown RPi		
#				down		normal RPi operation
#
# SWITCH_run_autonomous		up		Put car in autonomous mode
#				down		normal RPi operation
#
# SWITCH_collect_data		up		Start collecting data
#				down		Stop collection data if doing that		
#
# SWITCH_save_to_USBdrive	momentary up	Copy collected data to USB drive
#				down		normal RPi operation
#
# SWITCH_read_from_USBdrive	momentary up	Read training data to from USB drive
#				down		normal RPi operation
#

# -------- LED status cheatsheet --------- 
#
# 	SLOW blink -> WARNING ERROR
#	FAST blink -> FATAL ERROR
#
# LED				STATE		MEANING
# --------------------------------------------------------------
# LED_boot_RPi			OFF		No power to RPi		
#				ON		Turned on when RPi has finished booting
#				BLINKING	Not defined yet
#
# LED_shutdown_RPi		OFF		Not in use		
#				ON		System A-OK
#				BLINKING	Tried to shut down without copying collected data to USB drive
#
# LED_autonomous		OFF		Not in use		
#				ON		Car running autonomously
#				BLINKING	Autonomous error
#
# LED_collect_data		OFF		Not in use		
#				ON		Data collection in progress
#				BLINKING	Error during data collection
#
# LED_save_to_USBdrive		OFF		Not in use		
#				ON		Copy in progress
#				BLINKING	Error during copy
#
# LED_read_from_USBdrive	OFF		Not in use		
#				ON		Copy in progress
#				BLINKING	Error during read
#

# -------- LED functions to make code clearer --------- 
def turn_ON_LED( which_LED ):
	GPIO.output( which_LED, LED_ON )

def turn_OFF_LED( which_LED ):
	GPIO.output( which_LED, LED_OFF )	
	
g_Current_Exception_Not_Finished = False

# -------- Handler for clearing all switch errors --------- 
def handle_switch_exception( kindOfException, which_switch, which_LED, message ):

	global g_Current_Exception_Not_Finished
	
	if( g_Current_Exception_Not_Finished ):
		print( "*** another exception occurred" )
		
	else: 
		g_Current_Exception_Not_Finished = True
		print ( "" )
		print ( message )
		print("***", sys.exc_info()[0], "occured.")
		
		if( kindOfException == FATAL ):
			blinkSpeed = .1 
			switch_on_count = 6
	
		else:	
			blinkSpeed = .2
			switch_on_count = 3
		
		LED_state = LED_ON
		# blink the LED until the user holds down the button for 3 seconds
		error_not_cleared = True	
		while( error_not_cleared ):	
			if( GPIO.input( which_switch ) == PUSHED ):
				switch_on_count = switch_on_count - 1
				if( switch_on_count <= 0 ):
					error_not_cleared = False
				
			GPIO.output( which_LED, LED_state )	# blink the LED to show the error
			time.sleep( blinkSpeed )	
			LED_state = LED_state ^ 1		# xor bit 0 to toggle it from 0 to 1 to 0 ...

		turn_OFF_LED( which_LED )		# show the user the error has been cleared
	
		# don't leave until we're sure user released button	
		while True:
			time.sleep( blinkSpeed )		# executes delay at least once
			if ( GPIO.input( which_switch ) != PUSHED): break
	
		if( kindOfException == FATAL ):
			print( "*** FATAL exception handled" )
	
		else:	
			print( "*** WARNING exception handled" )
		
		g_Current_Exception_Not_Finished = False
	
# -------- define global variables which start with a little "g" --------- 
# -------------- Data Collector Global Variables -------------------------------
gWantsToSeeVideo = True
gCameraIsRecording = False
gRecordedDataNotSaved = False

# -------- Functions called by switch callback functions --------- 
def callback_switch_save_to_USBdrive( channel ): 
	# Contrary to the falling edge detection set up previously, sometimes an interrupt
	#	will occur on the RISING edge. These must be disregarded
	
	if( GPIO.input( SWITCH_save_to_USBdrive ) == PUSHED ): 
		
		try:
			turn_ON_LED( LED_save_to_USBdrive )
			switch_state = ON
			while ( switch_state == ON ):
				switch_state = GPIO.input( SWITCH_save_to_USBdrive )
	
			# do the copying ....
			raise Exception( "exception for debugging purposes" )
	
			turn_OFF_LED( LED_save_to_USBdrive )
		except:
			returnedError = NO_USB_DRIVE_WARNING	# **** set for debugging ****

			if( returnedError == NO_USB_DRIVE_WARNING ):			
				message = "copy to USB drive warning: USB drive not found"
				kindOfException = WARNING	
				
			else:			
				message = "copy to USB drive fatal error"
				kindOfException = FATAL	
			
			handle_switch_exception( kindOfException, SWITCH_save_to_USBdrive, LED_save_to_USBdrive, message )

	else: 
		print( "detected RISING EDGE interrupt on save to USB switch" )
	
# ------------------------------------------------- 
def callback_switch_read_from_USBdrive( channel ):
	# Contrary to the falling edge detection set up previously, sometimes an interrupt
	#	will occur on the RISING edge. These must be disregarded
	
	if( GPIO.input( SWITCH_read_from_USBdrive ) == PUSHED ): 
		
		try:
			turn_ON_LED( LED_read_from_USBdrive )
			switch_state = ON
			while ( switch_state == ON ):
				switch_state = GPIO.input( SWITCH_read_from_USBdrive )
	
			# do the reading ....
			raise Exception( "exception for debugging purposes" )
	
			turn_OFF_LED( LED_read_from_USBdrive )
		except:
			returnedError = NO_USB_DRIVE_WARNING	# **** set for debugging ****
			
			if( returnedError == NO_USB_DRIVE_WARNING ):			
				message = "read from USB drive warning: USB drive not found"
				kindOfException = WARNING	
				
			else:			
				print( "read error: I/O" )
				message = "read from USB drive fatal error"
				kindOfException = FATAL	
			
			handle_switch_exception( kindOfException, SWITCH_read_from_USBdrive, LED_read_from_USBdrive, message )

	else: 
		print( "detected RISING EDGE interrupt on read from USB switch" )
	 
# ------------------------------------------------- 
def callback_switch_autonomous( channel ):  
	# Contrary to the falling edge detection set up previously, sometimes an interrupt
	#	will occur on the RISING edge. These must be disregarded
	if( GPIO.input( SWITCH_run_autonomous ) == PUSHED ): 
		
		try:
			turn_ON_LED( LED_autonomous )
			switch_state = ON
			while ( switch_state == ON ):
				switch_state = GPIO.input( SWITCH_run_autonomous )
	
			# do the autonomous ....
			raise Exception( "exception for debugging purposes" )
	
			turn_OFF_LED( LED_autonomous )
		except:
			returnedError = FATAL	# **** set for debugging ****

			if( returnedError == AUTONOMOUS_WARNING ):			
				message = "autonomous error warning"
				kindOfException = WARNING	
				
			else:			
				message = "autonomous error fatal error"
				kindOfException = FATAL	
			
			handle_switch_exception( kindOfException, SWITCH_run_autonomous, LED_autonomous, message )

	else: 
		print( "detected RISING EDGE interrupt on autonomous switch" )
	 
# ------------------------------------------------- 
def callback_switch_shutdown_RPi( channel ):

	global gRecordedDataNotSaved

	# Contrary to the falling edge detection set up previously, sometimes an interrupt
	#	will occur on the RISING edge. These must be disregarded
	
	if( GPIO.input( SWITCH_shutdown_RPi ) == ON ): 
		try:
			turn_ON_all_LEDs( )
			# It takes two shutdown switch changes to shutdown when there is unsaved data
			if( gRecordedDataNotSaved ):
		
				# give another warning about not saving data
				if( gWasWarnedAboutNotSavingData == False ):
					gWasWarnedAboutNotSavingData = True
					raise Exception( "data not saved, first warning" )
			
				else:	# You were warned once about the unsaved data, too bad
					print( "shutdown with data unsaved" )
					time.sleep( 2 )		# leave the LED on for 2 seconds to show we did something
					turn_OFF_LED( LED_shutdown_RPi )	
	
			else:	
				print( "graceful shutdown" )
				time.sleep( 2 )		# leave the LED on for 2 seconds to show we did something
				turn_OFF_all_LEDs( )
	
		except:
			returnedError = RECORDED_DATA_NOT_SAVED	# **** set for debugging ****
		
			if( returnedError == RECORDED_DATA_NOT_SAVED ):			
				message = "shutdown error: recorded data not saved" 
				kindOfException = WARNING	
								
			handle_switch_exception( kindOfException, SWITCH_shutdown_RPi, LED_shutdown_RPi, message )

	else: 
		print( "detected RISING EDGE interrupt on shutdown switch" )
	 
# ------------------------------------------------- 
def callback_switch_collect_data( channel ):  
	global gRecordedDataNotSaved
	global gWantsToSeeVideo
	global gCameraIsRecording

	# Contrary to the falling edge detection set up previously, sometimes an interrupt
	#	will occur on the RISING edge. These must be disregarded
	if( GPIO.input( SWITCH_collect_data ) == ON ): 
		try:
			print( "* starting recording " )
			turn_ON_LED( LED_collect_data )
			
			collector=DataCollector()
			
			with picamera.PiCamera() as camera:
				#Note: these are just parameters to set up the camera, so the order is not important
				camera.resolution=(64, 64) #final image size
				camera.zoom=(.125, 0, .875, 1) #crop so aspect ratio is 1:1
				camera.framerate=10 #<---- framerate (fps) determines speed of data recording
				camera.start_recording( collector, format='rgb' )
				gCameraIsRecording = True
				if ( gWantsToSeeVideo ):
					camera.start_preview() #displays video while it's being recorded
				
				while( GPIO.input( SWITCH_collect_data ) == ON ):
					pass
					
				camera.stop_recording()
				gCameraIsRecording = False
				turn_OFF_LED( LED_collect_data )
				time.sleep( .1 )	# wait a little just in case the switch isn't stable
				
		except Exception as e:
			exc_type, exc_obj, exc_tb = sys.exc_info()
			fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
			print(exc_type, fname, "   line number = ", exc_tb.tb_lineno)			
			message = "* Data collection fatal error"
			kindOfException = FATAL	

			handle_switch_exception( kindOfException, SWITCH_collect_data, LED_collect_data, message )
	else: 
		print( "* detected another switch OFF interrupt" )
		if( gCameraIsRecording ):
			print( "  camera is still ON" )
		
		else:
			print( "  camera is turned OFF" )
				 	
# ------------------------------------------------- 
def turn_OFF_all_LEDs():
	turn_OFF_LED( LED_save_to_USBdrive )
	turn_OFF_LED( LED_read_from_USBdrive )
	turn_OFF_LED( LED_collect_data )
	turn_OFF_LED( LED_shutdown_RPi )
	turn_OFF_LED( LED_autonomous )
	turn_OFF_LED( LED_boot_RPi )
	 	
# ------------------------------------------------- 
def turn_ON_all_LEDs():
	turn_ON_LED( LED_save_to_USBdrive )
	turn_ON_LED( LED_read_from_USBdrive )
	turn_ON_LED( LED_collect_data )
	turn_ON_LED( LED_shutdown_RPi )
	turn_ON_LED( LED_autonomous )
	turn_ON_LED( LED_boot_RPi )
	 	
# ------------------------------------------------- 
def initialize_RPi_Stuff():
	
	# blink LEDs as an alarm if either switch has been left in the ON (up) position
	LED_state = LED_ON

	while(( GPIO.input( SWITCH_shutdown_RPi ) == ON ) or ( GPIO.input( SWITCH_collect_data ) == ON )):
		GPIO.output( LED_shutdown_RPi, LED_state )
		GPIO.output( LED_collect_data, LED_state )
		time.sleep( .25 )
		LED_state = LED_state ^ 1		# XOR bit to turn LEDs off or on
	
	# turn off all LEDs for initialization
	turn_OFF_all_LEDs()

# ---------------- MAIN PROGRAM ------------------------------------- 

GPIO.setmode( GPIO.BCM )  
GPIO.setwarnings( False )

#  falling edge detection setup for all switchs ( switchs or switches ) 
GPIO.setup( SWITCH_save_to_USBdrive, GPIO.IN, pull_up_down = GPIO.PUD_UP ) 
GPIO.setup( SWITCH_run_autonomous, GPIO.IN, pull_up_down = GPIO.PUD_UP ) 
GPIO.setup( SWITCH_read_from_USBdrive, GPIO.IN, pull_up_down = GPIO.PUD_UP ) 
GPIO.setup( SWITCH_shutdown_RPi, GPIO.IN, pull_up_down = GPIO.PUD_UP ) 
GPIO.setup( SWITCH_collect_data, GPIO.IN, pull_up_down = GPIO.PUD_UP ) 

GPIO.setup( LED_read_from_USBdrive, GPIO.OUT )
GPIO.setup( LED_save_to_USBdrive, GPIO.OUT )
GPIO.setup( LED_collect_data, GPIO.OUT )
GPIO.setup( LED_shutdown_RPi, GPIO.OUT )
GPIO.setup( LED_autonomous, GPIO.OUT )
GPIO.setup( LED_boot_RPi, GPIO.OUT )

GPIO.setup( OUTPUT_to_relay, GPIO.OUT )

# setup callback routines for switch falling edge detection  
#	NOTE: because of a RPi bug, sometimes a rising edge will also trigger these routines!
GPIO.add_event_detect( SWITCH_save_to_USBdrive, GPIO.FALLING, callback=callback_switch_save_to_USBdrive, bouncetime=50 )  
GPIO.add_event_detect( SWITCH_run_autonomous, GPIO.FALLING, callback=callback_switch_autonomous, bouncetime=50 )  
GPIO.add_event_detect( SWITCH_read_from_USBdrive, GPIO.FALLING, callback=callback_switch_read_from_USBdrive, bouncetime=50 )  
GPIO.add_event_detect( SWITCH_shutdown_RPi, GPIO.FALLING, callback=callback_switch_shutdown_RPi, bouncetime=50 )  
GPIO.add_event_detect( SWITCH_collect_data, GPIO.FALLING, callback=callback_switch_collect_data, bouncetime=50 ) 

initialize_RPi_Stuff()

turn_ON_LED( OUTPUT_to_relay )
turn_ON_LED( LED_boot_RPi )


while ( True ):	
#	turn_ON_LED( LED_read_from_USBdrive )
#	turn_OFF_LED( LED_save_to_USBdrive )
#	turn_ON_LED( LED_collect_data )
#	turn_OFF_LED( LED_autonomous )
#	time.sleep( .25 )

#	turn_OFF_LED( LED_read_from_USBdrive )
#	turn_ON_LED( LED_save_to_USBdrive )
#	turn_OFF_LED( LED_collect_data )
#	turn_ON_LED( LED_autonomous )
#	time.sleep( .25 )

	pass	
	
	
