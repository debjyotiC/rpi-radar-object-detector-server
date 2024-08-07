import serial
import time
import numpy as np
import os
from dependencies.database_class import DatabaseConnector
from dependencies.central_database_update import write_bunker_status

radar_type = 1642

CLIport = {}
Dataport = {}
byteBuffer = np.zeros(2 ** 15, dtype='uint8')
byteBufferLength = 0

script_dir = os.path.dirname(os.path.abspath(__file__))

if radar_type == 1642:
    configFileName = f"{script_dir}/config_files/AWR1642.cfg"
elif radar_type == 2944:
    configFileName = f"{script_dir}/config_files/AWR2944.cfg"

db_connector = DatabaseConnector(f"{script_dir}/database/radar_database.db")
db_connector.connect()
db_connector.create_schema()


# ------------------------------------------------------------------
def cell_averaging_peak_detector(matrix, threshold=0.5):
    row_means = np.mean(matrix, axis=1)
    max_values = np.max(matrix, axis=1)
    peak_values = (row_means + max_values) / 2
    peak_detected_matrix = np.zeros_like(matrix, dtype=int)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            if matrix[i, j] >= threshold and matrix[i, j] >= peak_values[i]:
                peak_detected_matrix[i, j] = 1
    return peak_detected_matrix


def range_profile_classifier(range_profile):
    range_profile = 20 * np.log10(range_profile)

    stacked_arr = np.vstack((range_profile,) * 10)
    img = cell_averaging_peak_detector(stacked_arr, threshold=70.1)

    ground_mask = np.ones(img.shape)
    ground_mask[:, :10] = 0

    img = img * ground_mask  # Broot force suppress ground clutter

    overall_sum = np.sum(img)

    thresh = 100.0  # change it according to your need

    if overall_sum > thresh:
        path_clearance = "path not clear"
        detected = "y"
    else:
        path_clearance = "path clear"
        detected = "n"

    obj_dict = {"Obj_Detected": path_clearance,
                "Obj_detection_flag": detected,
                "Threshold": thresh,
                "Sum": overall_sum,
                "Scene_Image": img.tolist()
                }
    debug_log = dict(list(obj_dict.items())[:4])
    db_connector.insert_data(obj_dict)

    if radar_type == 1642:
        write_bunker_status(detected)

    print(debug_log)


# Function to configure the serial ports and send the data from
# the configuration file to the radar
def serialConfig(configFileName):
    global CLIport
    global Dataport

    port_found = False

    while not port_found:
        try:
            # Open the serial ports for the configuration and the data ports

            # Raspberry Pi / Ubuntu
            # CLIport = serial.Serial('/dev/ttyACM0', 115200)
            # Dataport = serial.Serial('/dev/ttyACM1', 921600)

            # Windows
            # CLIport = serial.Serial('COM4', 115200)
            # Dataport = serial.Serial('COM5', 852272)

            if radar_type == 1642:
                CLIport = serial.Serial('/dev/ttyACM0', 115200)
                Dataport = serial.Serial('/dev/ttyACM1', 921600)
            elif radar_type == 2944:
                CLIport = serial.Serial('COM4', 115200)
                Dataport = serial.Serial('COM5', 852272)

            port_found = True

        except serial.SerialException:
            print("Serial port not found. Retrying in 1 second...")
            time.sleep(1)

    # Read the configuration file and send it to the board
    config = [line.rstrip('\r\n') for line in open(configFileName)]
    for i in config:
        CLIport.write((i + '\n').encode())
        print(i)
        time.sleep(0.01)

    return CLIport, Dataport


# ------------------------------------------------------------------

# Function to parse the data inside the configuration file
def parseConfigFile(configFileName):
    configParameters = {}  # Initialize an empty dictionary to store the configuration parameters

    # Read the configuration file and send it to the board
    config = [line.rstrip('\r\n') for line in open(configFileName)]
    for i in config:

        # Split the line
        splitWords = i.split(" ")

        # Hard code the number of antennas, change if other configuration is used
        numRxAnt = 4
        numTxAnt = 4

        # Get the information about the profile configuration
        if "profileCfg" in splitWords[0]:
            startFreq = int(float(splitWords[2]))
            idleTime = int(splitWords[3])
            rampEndTime = float(splitWords[5])
            freqSlopeConst = float(splitWords[8])
            numAdcSamples = int(splitWords[10])
            numAdcSamplesRoundTo2 = 1

            while numAdcSamples > numAdcSamplesRoundTo2:
                numAdcSamplesRoundTo2 = numAdcSamplesRoundTo2 * 2

            digOutSampleRate = int(splitWords[11])

        # Get the information about the frame configuration
        elif "frameCfg" in splitWords[0]:

            chirpStartIdx = int(splitWords[1])
            chirpEndIdx = int(splitWords[2])
            numLoops = int(splitWords[3])
            numFrames = int(splitWords[4])
            framePeriodicity = int(splitWords[5])

    # Combine the read data to obtain the configuration parameters
    numChirpsPerFrame = (chirpEndIdx - chirpStartIdx + 1) * numLoops
    configParameters["numDopplerBins"] = numChirpsPerFrame / numTxAnt
    configParameters["numRangeBins"] = numAdcSamplesRoundTo2
    configParameters["rangeResolutionMeters"] = (3e8 * digOutSampleRate * 1e3) / (
            2 * freqSlopeConst * 1e12 * numAdcSamples)
    configParameters["rangeIdxToMeters"] = (3e8 * digOutSampleRate * 1e3) / (
            2 * freqSlopeConst * 1e12 * configParameters["numRangeBins"])
    configParameters["dopplerResolutionMps"] = 3e8 / (
            2 * startFreq * 1e9 * (idleTime + rampEndTime) * 1e-6 * configParameters["numDopplerBins"] * numTxAnt)
    configParameters["maxRange"] = (300 * 0.9 * digOutSampleRate) / (2 * freqSlopeConst * 1e3)
    configParameters["maxVelocity"] = 3e8 / (4 * startFreq * 1e9 * (idleTime + rampEndTime) * 1e-6 * numTxAnt)

    return configParameters


# ------------------------------------------------------------------

# Funtion to read and parse the incoming data
def readAndParseData16xx(Dataport, configParameters):
    global byteBuffer, byteBufferLength

    # Constants
    OBJ_STRUCT_SIZE_BYTES = 12
    BYTE_VEC_ACC_MAX_SIZE = 2 ** 15
    MMWDEMO_UART_MSG_DETECTED_POINTS = 1
    MMWDEMO_UART_MSG_RANGE_PROFILE = 2
    MMWDEMO_OUTPUT_MSG_NOISE_PROFILE = 3
    MMWDEMO_OUTPUT_MSG_AZIMUT_STATIC_HEAT_MAP = 4
    MMWDEMO_OUTPUT_MSG_RANGE_DOPPLER_HEAT_MAP = 5
    maxBufferSize = 2 ** 15
    magicWord = [2, 1, 4, 3, 6, 5, 8, 7]

    # Initialize variables
    magicOK = 0  # Checks if magic number has been read
    dataOK = 0  # Checks if the data has been read correctly
    frameNumber = 0
    detObj = {}
    tlv_type = 0

    readBuffer = Dataport.read(Dataport.in_waiting)
    byteVec = np.frombuffer(readBuffer, dtype='uint8')
    byteCount = len(byteVec)

    # Check that the buffer is not full, and then add the data to the buffer
    if (byteBufferLength + byteCount) < maxBufferSize:
        byteBuffer[byteBufferLength:byteBufferLength + byteCount] = byteVec[:byteCount]
        byteBufferLength = byteBufferLength + byteCount

    # Check that the buffer has some data
    if byteBufferLength > 16:

        # Check for all possible locations of the magic word
        possibleLocs = np.where(byteBuffer == magicWord[0])[0]

        # Confirm that is the beginning of the magic word and store the index in startIdx
        startIdx = []
        for loc in possibleLocs:
            check = byteBuffer[loc:loc + 8]
            if np.all(check == magicWord):
                startIdx.append(loc)

        # Check that startIdx is not empty
        if startIdx:

            # Remove the data before the first start index
            if 0 < startIdx[0] < byteBufferLength:
                byteBuffer[:byteBufferLength - startIdx[0]] = byteBuffer[startIdx[0]:byteBufferLength]
                byteBuffer[byteBufferLength - startIdx[0]:] = np.zeros(len(byteBuffer[byteBufferLength - startIdx[0]:]),
                                                                       dtype='uint8')
                byteBufferLength = byteBufferLength - startIdx[0]

            # Check that there have no errors with the byte buffer length
            if byteBufferLength < 0:
                byteBufferLength = 0

            # word array to convert 4 bytes to a 32-bit number
            word = [1, 2 ** 8, 2 ** 16, 2 ** 24]

            # Read the total packet length
            totalPacketLen = np.matmul(byteBuffer[12:12 + 4], word)

            # Check that all the packet has been read
            if (byteBufferLength >= totalPacketLen) and (byteBufferLength != 0):
                magicOK = 1

    # If magicOK is equal to 1 then process the message
    if magicOK:
        # word array to convert 4 bytes to a 32-bit number
        word = [1, 2 ** 8, 2 ** 16, 2 ** 24]

        # Initialize the pointer index
        idX = 0

        # Read the header
        magicNumber = byteBuffer[idX:idX + 8]
        idX += 8
        version = format(np.matmul(byteBuffer[idX:idX + 4], word), 'x')
        idX += 4
        totalPacketLen = np.matmul(byteBuffer[idX:idX + 4], word)
        idX += 4
        platform = format(np.matmul(byteBuffer[idX:idX + 4], word), 'x')
        idX += 4
        frameNumber = np.matmul(byteBuffer[idX:idX + 4], word)
        idX += 4
        timeCpuCycles = np.matmul(byteBuffer[idX:idX + 4], word)
        idX += 4
        numDetectedObj = np.matmul(byteBuffer[idX:idX + 4], word)
        idX += 4
        numTLVs = np.matmul(byteBuffer[idX:idX + 4], word)
        idX += 4
        subFrameNumber = np.matmul(byteBuffer[idX:idX + 4], word)
        idX += 4

        # Read the TLV messages
        for tlvIdx in range(numTLVs):

            # word array to convert 4 bytes to a 32-bit number
            word = [1, 2 ** 8, 2 ** 16, 2 ** 24]

            # Check the header of the TLV message
            try:
                tlv_type = np.matmul(byteBuffer[idX:idX + 4], word)
                idX += 4
                tlv_length = np.matmul(byteBuffer[idX:idX + 4], word)
                idX += 4
            except:
                pass

            # Read the data depending on the TLV message
            if tlv_type == MMWDEMO_UART_MSG_DETECTED_POINTS:

                # word array to convert 4 bytes to a 16-bit number
                word = [1, 2 ** 8]
                tlv_numObj = np.matmul(byteBuffer[idX:idX + 2], word)
                idX += 2
                tlv_xyzQFormat = 2 ** np.matmul(byteBuffer[idX:idX + 2], word)
                idX += 2

                # Initialize the arrays
                rangeIdx = np.zeros(tlv_numObj, dtype='int16')
                dopplerIdx = np.zeros(tlv_numObj, dtype='int16')
                peakVal = np.zeros(tlv_numObj, dtype='int16')
                x = np.zeros(tlv_numObj, dtype='int16')
                y = np.zeros(tlv_numObj, dtype='int16')
                z = np.zeros(tlv_numObj, dtype='int16')

                for objectNum in range(tlv_numObj):
                    # Read the data for each object
                    rangeIdx[objectNum] = np.matmul(byteBuffer[idX:idX + 2], word)
                    idX += 2
                    dopplerIdx[objectNum] = np.matmul(byteBuffer[idX:idX + 2], word)
                    idX += 2
                    peakVal[objectNum] = np.matmul(byteBuffer[idX:idX + 2], word)
                    idX += 2
                    x[objectNum] = np.matmul(byteBuffer[idX:idX + 2], word)
                    idX += 2
                    y[objectNum] = np.matmul(byteBuffer[idX:idX + 2], word)
                    idX += 2
                    z[objectNum] = np.matmul(byteBuffer[idX:idX + 2], word)
                    idX += 2

                # Make the necessary corrections and calculate the rest of the data
                rangeVal = rangeIdx * configParameters["rangeIdxToMeters"]
                dopplerIdx[dopplerIdx > (configParameters["numDopplerBins"] / 2 - 1)] = dopplerIdx[dopplerIdx > (
                        configParameters["numDopplerBins"] / 2 - 1)] - 65535
                dopplerVal = dopplerIdx * configParameters["dopplerResolutionMps"]
                x = x / tlv_xyzQFormat
                y = y / tlv_xyzQFormat
                z = z / tlv_xyzQFormat

                # Store the data in the detObj dictionary
                detObj = {"numObj": tlv_numObj, "rangeIdx": rangeIdx, "range": rangeVal, "dopplerIdx": dopplerIdx,
                          "doppler": dopplerVal, "peakVal": peakVal, "x": x, "y": y, "z": z}

                dataOK = 1

            elif tlv_type == MMWDEMO_UART_MSG_RANGE_PROFILE:
                rangeProfile = np.frombuffer(byteBuffer[idX:idX + (tlv_length - 8)], dtype=np.uint16)
                idX += (tlv_length - 8)
                range_profile_classifier(rangeProfile)

            elif tlv_type == MMWDEMO_OUTPUT_MSG_RANGE_DOPPLER_HEAT_MAP:
                # Get the number of bytes to read
                numBytes = int(2 * configParameters["numRangeBins"] * configParameters["numDopplerBins"])
                # Convert the raw data to int16 array
                payload = byteBuffer[idX:idX + numBytes]
                idX += numBytes
                rangeDoppler = payload.view(dtype=np.int16)

                # Some frames have strange values, skip those frames
                # TO DO: Find why those strange frames happen
                if np.max(rangeDoppler) > 10000:
                    continue

                # Convert the range doppler array to a matrix
                rangeDoppler = np.reshape(rangeDoppler, (
                    int(configParameters["numDopplerBins"]), int(configParameters["numRangeBins"])),
                                          'F')  # Fortran-like reshape
                rangeDoppler = np.append(rangeDoppler[int(len(rangeDoppler) / 2):],
                                         rangeDoppler[:int(len(rangeDoppler) / 2)], axis=0)
                rangeDoppler = 20 * np.log10(rangeDoppler)
                # Generate the range and doppler arrays for the plot
                rangeArray = np.array(range(configParameters["numRangeBins"])) * configParameters["rangeIdxToMeters"]
                dopplerArray = np.multiply(
                    np.arange(-configParameters["numDopplerBins"] / 2, configParameters["numDopplerBins"] / 2),
                    configParameters["dopplerResolutionMps"])

        # Remove already processed data
        if 0 < idX < byteBufferLength:
            shiftSize = totalPacketLen

            byteBuffer[:byteBufferLength - shiftSize] = byteBuffer[shiftSize:byteBufferLength]
            byteBuffer[byteBufferLength - shiftSize:] = np.zeros(len(byteBuffer[byteBufferLength - shiftSize:]),
                                                                 dtype='uint8')
            byteBufferLength = byteBufferLength - shiftSize

            # Check that there are no errors with the buffer length
            if byteBufferLength < 0:
                byteBufferLength = 0

    return dataOK, frameNumber, detObj


# -------------------------    MAIN   -----------------------------------------

# Configurate the serial port
CLIport, Dataport = serialConfig(configFileName)

# Get the configuration parameters from the configuration file
configParameters = parseConfigFile(configFileName)

# Main loop
detObj = {}
frameData = {}
currentIndex = 0
while True:
    try:
        dataOk, frameNumber, detObj = readAndParseData16xx(Dataport, configParameters)

        if dataOk:
            # Store the current frame into frameData
            frameData[currentIndex] = detObj
            currentIndex += 1

        time.sleep(0.04)  # Sampling frequency of 40 Hz

    # Stop the program and close everything if Ctrl + c is pressed
    except KeyboardInterrupt:
        CLIport.write('sensorStop\n'.encode())
        CLIport.close()
        Dataport.close()
        break
