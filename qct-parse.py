#qct-parse3.2 -> fixed bugs in 3.1

#see this link for lxml goodness: http://www.ibm.com/developerworks/xml/library/x-hiperfparse/

from lxml import etree  #for reading XML file (you will need to install this with pip)
import argparse         #for parsing input args
import ConfigParser		#grip frame data values from a config txt file
import gzip             #for opening gzip file
import logging          #for logging output
import collections      #for circular buffer
import os      			#for running ffmpeg and other terminal commands
import subprocess		#not currently used
import gc				#not currently used
import math				#used for rounding up buffer half
import sys				#system stuff
import re				#can't spell parse without re fam
from distutils import spawn #dependency checking

#check that we have required software installed
def dependencies():
	depends = ['ffmpeg','ffprobe']
	for d in depends:
		if spawn.find_executable(d) is None:
			print "Buddy, you gotta install " + d
			sys.exit()
	return

#Creates timestamp for pkt_dts_time
def dts2ts(frame_pkt_dts_time):
    seconds = float(frame_pkt_dts_time)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours < 10:
        hours = "0" + str(int(hours))
    else:
        hours = str(int(hours))  
    if minutes < 10:
        minutes = "0" + str(int(minutes))
    else:
        minutes = str(int(minutes))
    secondsStr = str(round(seconds,4))
    if int(seconds) < 10:
        secondsStr = "0" + secondsStr
    else:
        seconds = str(minutes)
    while len(secondsStr) < 7:
        secondsStr = secondsStr + "0"
    timeStampString = hours + ":" + minutes + ":" + secondsStr
    return timeStampString

#initializes the log
def initLog(inputPath):
	logPath = inputPath + '.log'
	logging.basicConfig(filename=logPath,level=logging.INFO,format='%(asctime)s %(message)s')
	logging.info("Started QCT-Parse")
	
#finds overs
def overFinder(inFrame,args,startObj,tag,over,thumbPath,thumbDelay):
	tagValue = float(inFrame[tag])
	frame_pkt_dts_time = inFrame['pkt_dts_time']
	if tagValue > float(over): #if the attribute is over usr set threshold
		timeStampString = dts2ts(frame_pkt_dts_time)
		logging.warning(tag + " is over " + str(over) + " with a value of " + str(tagValue) + " at duration " + timeStampString)
		if args.te and (thumbDelay > int(args.ted)): #if thumb export is turned on and there has been enough delay between this frame and the last exported thumb, then export a new thumb
			printThumb(args,startObj,thumbPath,tagValue,timeStampString)
			thumbDelay = 0
		return True, thumbDelay #return true because it was over and thumbDelay
	return False, thumbDelay #return false because it was NOT over and thumbDelay

#print thumbnail images of overs/unders	
def printThumb(args,startObj,thumbPath,tagValue,timeStampString):
	####init some variables using the args list
	inputVid = startObj.replace(".qctools.xml.gz", "")
	baseName = os.path.basename(startObj)
	baseName = baseName.replace(".qctools.xml.gz", "")
	outputFramePath = os.path.join(thumbPath,baseName + "." + args.t + "." + str(tagValue) + "." + timeStampString + ".png")
	ffoutputFramePath = outputFramePath.replace(":",".")
	#for windows we gotta see if that first : for the drive has been replaced by a dot and put it back
	match = ''
	match = re.search(r"[A-Z]\.\/",ffoutputFramePath) #matches pattern R./ which should be R:/ on windows
	if match:
		ffoutputFramePath = ffoutputFramePath.replace(".",":",1) #replace first instance of "." in string ffoutputFramePath
	ffmpegString = "ffmpeg -ss " + timeStampString + " -i " + inputVid +  " -vframes 1 -y " + ffoutputFramePath
	output = subprocess.Popen(ffmpegString,stdout=subprocess.PIPE,stderr=subprocess.PIPE) #,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=True
	out,err = output.communicate()
	if args.q is False:
		print out
		print err
	return	
	
#detect bars	
def detectBars(args,startObj,durationStart,durationEnd,framesList,buffSize):
	with gzip.open(startObj) as xml:
		for event, elem in etree.iterparse(xml, events=('end',), tag='frame'): #iterparse the xml doc
			if elem.attrib['media_type'] == "video": #get just the video frames
				frame_pkt_dts_time = elem.attrib['pkt_dts_time'] #get the timestamps for the current frame we're looking at
				frameDict = {}  #start an empty dict for the new frame
				frameDict['pkt_dts_time'] = frame_pkt_dts_time  #give the dict the timestamp, which we have now
				for t in list(elem):    #iterating through each attribute for each element
					keySplit = t.attrib['key'].split(".")   #split the names by dots 
					keyName = str(keySplit[-1])             #get just the last word for the key name
					frameDict[keyName] = t.attrib['value']	#add each attribute to the frame dictionary
				framesList.append(frameDict)
				middleFrame = int(round(float(len(framesList))/2))	#i hate this calculation, but it gets us the middle index of the list as an integer
				if len(framesList) == buffSize:	#wait till the buffer is full to start detecting bars
					##This is where the bars detection magic actually happens
					bufferRange = range(0, buffSize)
					if int(framesList[middleFrame]['YMAX']) > 210 and int(framesList[middleFrame]['YMIN']) < 10 and float(framesList[middleFrame]['YDIF']) < 3.0:
						if durationStart == "":
							durationStart = float(framesList[middleFrame]['pkt_dts_time'])
							print "Bars start at " + str(framesList[middleFrame]['pkt_dts_time']) + " (" + dts2ts(framesList[middleFrame]['pkt_dts_time']) + ")"							
						durationEnd = float(framesList[middleFrame]['pkt_dts_time'])
					else:
						print "Bars ended at " + str(framesList[middleFrame]['pkt_dts_time']) + " (" + dts2ts(framesList[middleFrame]['pkt_dts_time']) + ")"							
						break
			elem.clear() #we're done with that element so let's get it outta memory
	return

def analyzeIt(args,profile,startObj,durationStart,durationEnd,thumbPath,thumbDelay,framesList,frameCount=0):
	kover = {} #init a dict for each key which we'll use to track how often a given key is over
	for k,v in profile.iteritems(): 
		kover[k] = 0
	with gzip.open(startObj) as xml:	
		for event, elem in etree.iterparse(xml, events=('end',), tag='frame'): #iterparse the xml doc
			if elem.attrib['media_type'] == "video": #get just the video frames
				frameCount = frameCount + 1
				frame_pkt_dts_time = elem.attrib['pkt_dts_time'] #get the timestamps for the current frame we're looking at
				if float(frame_pkt_dts_time) >= durationStart:	#only work on frames that are after the start time
					if float(frame_pkt_dts_time) > durationEnd:	#only work on frames that are before the end time
						print "started at " + str(durationStart) + " seconds and stopped at " + str(frame_pkt_dts_time) + " seconds (" + dts2ts(frame_pkt_dts_time) + ") or " + str(count) + " frames!"
						break
					frameDict = {}  								#start an empty dict for the new frame
					frameDict['pkt_dts_time'] = frame_pkt_dts_time  #make a key for the timestamp, which we have now
					for t in list(elem):    						#iterating through each attribute for each element
						keySplit = t.attrib['key'].split(".")   	#split the names by dots 
						keyName = str(keySplit[-1])             	#get just the last word for the key name
						frameDict[keyName] = t.attrib['value']		#add each attribute to the frame dictionary
					framesList.append(frameDict)					#add this dict to our circular buffer
					if args.p is True:	#display "timestamp: Tag Value" (654.754100: YMAX 229) to the terminal window
						print framesList[-1]['pkt_dts_time'] + ": " + args.t + " " + framesList[-1][args.t]
					#Now we can parse the frame data from the buffer!	
					#use the overFinder() function to find overs
					#frameOver = 0
					if args.o and args.uc is None:
						tag = args.t
						over = float(args.o)
						frameOver, thumbDelay = overFinder(framesList[-1],args,startObj,tag,over,thumbPath,thumbDelay)
						if frameOver is True:
							kover[tag] = kover[tag] + 1
					elif args.uc is not None:
						for k,v in profile.iteritems():
							tag = k
							over = float(v)
							frameOver, thumbDelay = overFinder(framesList[-1],args,startObj,tag,over,thumbPath,thumbDelay)
							if frameOver is True:
								kover[k] = kover[k] + 1
					thumbDelay = thumbDelay + 1					
			elem.clear() #we're done with that element so let's get it outta memory
	for k,v in profile.iteritems():
		print k
		print kover[k]
	return kover, frameCount


	
def printresults(kover,frameCount):
	if frameCount == 0:
		percentOverString = "0"
	else:
		for k,v in kover.iteritems():
			percentOver = float(kover[k]) / float(frameCount)
			if percentOver == 1:
				percentOverString = "100"
			else:
				percentOverString = str(percentOver)
				percentOverString = percentOverString[2:4] + "." + percentOverString[4:]
				print "Number of frames over threshold for key " + k + " = " + str(kover[k])
				print "Which is " + percentOverString + "% of the total # of frames"
				#print "##############################################################"
				print ""
	return
	
def main():
	####init the stuff from the cli########
	parser = argparse.ArgumentParser(description="parses QCTools XML files for frames beyond broadcast values")
	parser.add_argument('-i','--input',dest='i', help="the path to the input qctools.xml.gz file")
	parser.add_argument('-t','--tagname',dest='t', help="the tag name you want to test, e.g. SATMAX")
	parser.add_argument('-o','--over',dest='o', help="the threshold overage number")
	parser.add_argument('-u','--under',dest='u', help="the threshold under number")
	parser.add_argument('-uc','--useconfig',dest='uc',default=None,help="use values from your qct-parse-config.txt file, provide profile/ template name, e.g. 'default'")
	parser.add_argument('-buff','--buffSize',dest='buff',default=11, help="Size of the circular buffer. if user enters an even number it'll default to the next largest number to make it odd (default size 11)")
	parser.add_argument('-te','--thumbExport',dest='te',action='store_true',default=False, help="export thumbnail")
	parser.add_argument('-ted','--thumbExportDelay',dest='ted',default=9000, help="minimum frames between exported thumbs")
	parser.add_argument('-tep','--thumbExportPath',dest='tep',default='', help="Path to thumb export. if ommitted, it uses the input basename")
	parser.add_argument('-ds','--durationStart',dest='ds',default=0, help="the duration in seconds to start analysis")
	parser.add_argument('-de','--durationEnd',dest='de',default=99999999, help="the duration in seconds to stop analysis")
	parser.add_argument('-bd','--barsDetection',dest='bd',action ='store_true',default=False, help="turns Bar Detection on and off")
	parser.add_argument('-p','--print',dest='p',action='store_true',default=False, help="print over/under frame data to console window")
	parser.add_argument('-q','--quiet',dest='q',action='store_true',default=False, help="hide ffmpeg output from console window")
	args = parser.parse_args()
	
	
	######Initialize values from the Config Parser
	profile = {} #init a dictionary where we'll store reference values from our config file
	if args.uc is not None:
		config = ConfigParser.ConfigParser()
		dn, fn = os.path.split(os.path.abspath(__file__)) #grip the dir where ~this script~ is located, also where config.txt should be located
		config.read(os.path.join(dn,"qct-parse_config.txt"))
		template = args.uc
		#don't have an underFinder function yet lol
		#profile['YMIN'] = config.get(template,'y_min')
		profile['YMAX'] = config.get(template,'y_max')
		#profile['UMIN'] = config.get(template,'u_min')
		profile['UMAX'] = config.get(template,'u_max')
		#profile['VMIN'] = config.get(template,'v_min')
		profile['VMAX'] = config.get(template,'v_max')
		profile['SATMAX'] = config.get(template,'sat_max')
		profile['TOUT'] = config.get(template,'tout_max')
		profile['VREP'] = config.get(template,'vrep_max')
	
	
	######Initialize some other stuff######
	startObj = args.i.replace("\\","/")
	buffSize = int(args.buff)   #cast the input buffer as an integer
	if buffSize%2 == 0:
		buffSize = buffSize + 1
	initLog(startObj)	#initialize the log
	overcount = 0	#init count of overs
	undercount = 0	#init count of unders
	count = 0		#init total frames counter
	framesList = collections.deque(maxlen=buffSize)		#init holding object for holding all frame data in a circular buffer. 
	bdFramesList = collections.deque(maxlen=buffSize) 	#init holding object for holding all frame data in a circular buffer. 
	thumbDelay = int(args.ted)	
	parentDir = os.path.dirname(startObj)
	baseName = os.path.basename(startObj)
	baseName = baseName.replace(".qctools.xml.gz", "")
	durationStart = args.ds
	durationEnd = args.de

	
	#set the start and end duration times
	if args.bd:
		durationStart = ""				#if bar detection is turned on then we have to calculate this
		durationEnd = ""				#if bar detection is turned on then we have to calculate this
	elif args.ds:
		durationStart = float(args.ds) 	#The duration at which we start analyzing the file if no bar detection is selected
	elif not args.de == 99999999:
		durationEnd = float(args.de) 	#The duration at which we stop analyzing the file if no bar detection is selected
	
	
	#set the path for the thumbnail export	
	if args.tep and not args.te:
		print "Buddy, you specified a thumbnail export path without specifying that you wanted to export the thumbnails. Please either add '-te' to your cli call or delete '-tep [path]'"
	
	if args.tep:
	    thumbPath = str(args.tep)
	else:
		thumbPath = os.path.join(parentDir, str(args.t) + "." + str(args.o))

	if args.te:
		if not os.path.exists(thumbPath):
			os.makedirs(thumbPath)
	
	
	########Iterate Through the XML for Bars detection########
	if args.bd:
		print "Starting Bars Detection on " + baseName
		print ""
		detectBars(args,startObj,durationStart,durationEnd,framesList,buffSize)
	

	########Iterate Through the XML for General Analysis########
	print "Starting Analysis on " + baseName
	print ""
	kover, frameCount = analyzeIt(args,profile,startObj,durationStart,durationEnd,thumbPath,thumbDelay,framesList)
	
	
	print "Finished Processing File: " + baseName + ".qctools.xml.gz"
	print ""
	
	
	#do some maths for the printout
	if args.o or args.uc is not None:
		printresults(kover,frameCount)
	
	return

dependencies()	
main()

