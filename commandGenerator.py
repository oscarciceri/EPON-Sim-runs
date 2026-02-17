#!/usr/bin/venv python

import numpy as np
import json
import math 
import os

def get_seed(seed_id):
	db_seeds = [1973272912,  188312339, 1072664641,  694388766,
	        2009044369,  934100682, 1972392646, 1936856304,
	        1598189534, 1822174485, 1871883252,  558746720,
	        605846893, 1384311643, 2081634991, 1644999263,
	        773370613,  358485174, 1996632795, 1000004583,
	        1769370802, 1895218768,  186872697, 1859168769,
	        349544396, 1996610406,  222735214, 1334983095,
	        144443207,  720236707,  762772169,  437720306,
	        939612284,  425414105, 1998078925,  981631283,
	        1024155645,  822780843,  701857417,  960703545,
	        2101442385, 2125204119, 2041095833,   89865291,
	        898723423, 1859531344,  764283187, 1349341884,
	        678622600,  778794064, 1319566104, 1277478588,
	        538474442,  683102175,  999157082,  985046914,
	        722594620, 1695858027, 1700738670, 1995749838,
	        1147024708,  346983590,  565528207,  513791680];
	return db_seeds[seed_id]


def create_file(directory, name, value):
	if os.path.exists(directory+name+".txt"):
		os.remove(directory+name+".txt")

	resultFile = open(directory+name+".txt", 'a')
	resultFile.write("{}".format(value,'\n'))
	resultFile.close()



if __name__ == "__main__":
	print("*** Generador de Comandos ***\n")




	# Parameters for repeat the simulation
	numSeeds = 1;
	seeds = np.arange(numSeeds)
	


	# Parameters for the simulation
	directory         = "/home/oscar/a_tasks/";
	nomejar           = "EPON-Sim.jar";
	finishTime        = 1000.0;         # In seconds
	guardTime         = 0.000000624;   # 2 us o 1 us for 10G-EPON, 5 us for EPON, now 624 ns
	nOnus             = 64;            # Number of ONUs
	opticalLinkSpeed  = 25000000000;   # Bit rate per wavelengths = 25  Gbps
	nWaves            = 2              # Number of wavelengths
	sizeOfONUSBuffers = 100;           # 100 Mbytes for 10G-EPON, 10 Mbytes for EPON
	maxCycleLength    = 0.001;         # 1 ms for 50G-EPON, 10ms, 5ms, 2ms for EPON
	
	load  = [55, 60, 65, 70, 75, 80, 85];           # % of load of every ONU that do NOT below to group. If 100% => Congestion in the back-hauling
	
	algortimos = ["IPACT"]
	taxonomias = ["FirstFit"]
	scheduling = ["LIMITED"]
	frameworks = ["ONLINE"]
	intrasched = ["STRICTPRIORITY"] #,"LEAKYBUCKET", "LBCONSTANTTOKENSBYCYCLE", "LBVARIBLETOKENSBYCYCLE", "STRICTPRIORITYFIRSTAF"]
	epoch_rounds = {
	    1: 68,
	    2: 40,
	    3: 36,
	    4: 30,
	    5: 28
	}

	# Parameters for ONUs that below to group
	# Maximum windows size
	windows_onu = (maxCycleLength - nOnus*guardTime)/nOnus
	print("Maximum windows size per ONU: ", windows_onu)

	# Bandwidth
	average_bandwidth = windows_onu*opticalLinkSpeed*nWaves;
	print("***Bandwidth per ONU: ", average_bandwidth)
	for i_alg in algortimos:
		for i_intra in intrasched:
			for i_epoch in epoch_rounds.keys():
				for i_load in load:
					for i_seed in seeds:

						name = []
						name =  str(i_alg) + "_"           
						name += str(i_intra) + "_"
						name += str(i_epoch) + "_"
						name += str(epoch_rounds[i_epoch]) + "_"
						name += str(i_load) + "_"
						name += str(i_seed) 


						comandoJava = []

						comandoJava = "java -jar " + nomejar 
						comandoJava += " ALG " + i_alg 
						comandoJava += " TAX FirstFit"
						comandoJava += " GSP LIMITED" 
						comandoJava += " GSF ONLINE"
						comandoJava += " INTRA " + i_intra 
						comandoJava += " CYCLE " + str(maxCycleLength)
						comandoJava += " GUARD_BAND " + str(guardTime)
						comandoJava += " NUMBER_ONUS " + str(nOnus)
						comandoJava += " ONU_LOAD " + str((i_load*0.01*average_bandwidth)/1000)
						comandoJava += " OPTICAL_SPEED " + str(opticalLinkSpeed)
						comandoJava += " FINISH_TIME " + str(finishTime)
						comandoJava += " SEED " + str(get_seed(i_seed))
						comandoJava += " EPOCH " + str(i_epoch)
						comandoJava += " N_ROUNDS " + str(epoch_rounds[i_epoch])
						comandoJava += " FILENAME " + name


						print(comandoJava)
						create_file(directory, name, comandoJava)








