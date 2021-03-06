import numpy as np
import matplotlib.pyplot as plt
import re
import pickle
from scipy import special as sp
from tabulate import tabulate
import math as mp
from sun_moon import find_sun_moon_acc, position_sun_moon
from solar_radiation import get_solar_radiation_petrubation
from atmo_drag import find_drag_petrubation, doorbnos_drag
from pylab import rcParams
from state_kep import state_kep
from anom_conv import true_to_ecc, ecc_to_mean, mean_to_t
from teme_to_ecef import conv_to_ecef
import pandas as pd
import datetime
import timeit


class propagator():

	def __init__(self):
		self.accelerations = np.zeros((5, 3))
		self.keepAccelerations = []
		self.keepStateVectors = []
		self.epochs = []
		self.C = np.zeros(1)
		self.S = np.zeros(1)

	def restruct_geopotential_file(self, gravityModelFileName):
		"""Creates a new restructured file holding the geopotential coefficients Cnm,Snm of a gravity model
			Args:
				gravityModelFileName (string): the name of the file holding the coeffs
		"""

		handler = open(gravityModelFileName, 'r')
		writeHandler = open("restruct_" + gravityModelFileName, "a")
		for line in handler:
			reStructLine = re.sub("\s+", ",", line.strip())
			writeHandler.write(reStructLine)
			writeHandler.write("\n")

		handler.close()
		writeHandler.close()

	def read_geopotential_coeffs(self, restructGravityFileName, firstRead):
		"""Returns an array holding the geopotential coefficients Cnm,Snm of a gravity model
			Args:
				gravityModelFileName (string): the name of the file holding the coeffs
				firstRead (boolean): if you are using this method the first time or the .p file has been created already
			Returns:
				nxm numpy array: coeffs in proper format to be used by ydot_geopotential
		"""

		if firstRead is True:

			data = np.genfromtxt(restructGravityFileName, delimiter=",")
			data = data[1:, 1:]

			pickle.dump(data, open("data " + restructGravityFileName + ".p", "wb"))
		elif firstRead is False:

			data = pickle.load(open("data " + restructGravityFileName + ".p", "rb"))

		return data

	def cart2geodetic(self, x, y, z):
		"""cartesian to geodetic coordinates transformation ellipsoid used WGS84
			Args:
				x (float)
				y (float)
				z (float)
			Returns:
				r (float)
				phi (float)
				l (float)
		"""

		a = 6378137
		f = 1 / 298.257223563
		b = a - f*a
		e = mp.sqrt(2*f - f**2)
		epsilon = mp.sqrt((a**2 - b**2) / b**2)
		p = mp.sqrt(x**2 + y**2)
		theta = mp.atan2((z*a), (p*b))

		phi = mp.atan2((z + (epsilon**2)*b*mp.sin(theta)**3), (p - (e**2)*a*mp.cos(theta)**3))
		l = mp.atan2(y, x)
		r = p / mp.cos(phi) - (a / mp.sqrt(1-(e**2)*mp.sin(phi)**2))

		return r, phi, l

	def createNumpyArrayForCoeffs(self, gravityCoeff, n, m):
		"""
			Return Cnm and Snm in separate numpy arrays for certain degree n and order m
		"""
		C = np.zeros((n+1, m+1))
		S = np.zeros((n+1, m+1))

		for i in range(0, len(gravityCoeff)):
			nIndex = gravityCoeff[i, 0]
			mIndex = gravityCoeff[i, 1]

			if (nIndex > n) or (mIndex > m):
				continue
			else:
				C[int(nIndex), int(mIndex)] = gravityCoeff[i, 2]
				S[int(nIndex), int(mIndex)] = gravityCoeff[i, 3]

		C[0, 0] = 1
		self.C = np.copy(C)
		self.S = np.copy(S)
		self.n = n
		self.m = m

	def ydot_geopotential(self, y, C, S, n, m):
		"""Returns the time derivative of only the geopotential effect for a given state.
		!!! Deprecated Method!!!
			Args:
				y(1x6 numpy array): the state vector [rx,ry,rz,vx,vy,vz]
				gravityCoeff (nxm numpy array): the array where you have stored the geopotential coefficients Cnm,Snm
				n (integer): degree of coeffs you want to use for the calculation
				m (integer): order of coeffs you want to use for the calculation
			Returns:
				1x6 numpy array: the time derivative of y [vx,vy,vz,ax,ay,az]
		"""

		r, phi, l = self.cart2geodetic(y[0], y[1], y[2])

		earthR = 6378137
		mu = 398600.4405e+09

		r = r + earthR

		legendreP = sp.lpmn(n+1, m+1, mp.sin(phi))
		legendreP = legendreP[0]
		legendreP = np.transpose(legendreP)
		V = np.zeros((n+1, m+1))
		W = np.zeros((n+1, m+1))

		for i in range(0, n+1):
			for j in range(0, i+1):

				V[i, j] = ((earthR/r) ** (i+1)) * (legendreP[i, j] * mp.cos(j * l))
				W[i, j] = ((earthR/r) ** (i+1)) * (legendreP[i, j] * mp.sin(j * l))

		ax = 0
		ay = 0
		az = 0
		for i in range(0, n-2):
			for j in range(0, i+1):

				if j == 0:
					ax = ax + (mu / earthR**2) * (-C[i, 0] * V[i+1, 1])

					ay = ay + (mu / earthR ** 2) * (-C[i, 0] * W[i + 1, 1])
				else:
					ax = ax + (mu / earthR ** 2) * 0.5 * (-C[i, j] * V[i + 1, j + 1] - S[i, j] * W[i + 1, j + 1]) + \
						 (mp.factorial(i - j + 2) / mp.factorial(i - j)) * (
						 C[i, j] * V[i + 1, j - 1] + S[i, j] * W[i + 1, j - 1])

					ay = ay + (mu / earthR ** 2) * 0.5 * (-C[i, j] * W[i + 1, j + 1] + S[i, j] * V[i + 1, j + 1]) + \
					     (mp.factorial(i - j + 2) / mp.factorial(i - j)) * (
						 -C[i, j] * W[i + 1, j - 1] + S[i, j] * V[i + 1, j - 1])

				az = az + (mu / earthR ** 2) * ((i-j+1) * (-C[i, j] * V[i+1, j] - S[i, j] * W[i+1, j]))

		ax = -ax
		ay = -ay
		# print(ax, ay, az)
		return np.array([ax, ay, az])

	def geodynamic_model(self, y, C, S, n, m):
		"""
		Compute the acceleration coming from Earth and a Geodynamic Model
		with C,S and order n and class m
		"""

		mu = 398600.4405e+09
		R_ref = 6378137
		r_sqr = np.dot(y[0:3], y[0:3])
		rho = R_ref * R_ref / r_sqr

		x0 = R_ref * y[0] / r_sqr
		y0 = R_ref * y[1] / r_sqr
		z0 = R_ref * y[2] / r_sqr

		V = np.zeros((n + 2, m + 2))
		W = np.zeros((n + 2, m + 2))

		V[0, 0] = R_ref / np.sqrt(r_sqr)
		W[0, 0] = 0.0

		V[1, 0] = z0 * V[0, 0]
		W[1, 0] = 0.0

		for i in range(2, n + 2):
			V[i, 0] = ((2 * i - 1) * z0 * V[i - 1, 0] - (i - 1) * rho * V[i - 2, 0]) / i
			W[i, 0] = 0.0

		for j in range(1, m + 2):

			V[j, j] = (2 * j - 1) * (x0 * V[j - 1, j - 1] - y0 * W[j - 1, j - 1])
			W[j, j] = (2 * j - 1) * (x0 * W[j - 1, j - 1] + y0 * V[j - 1, j - 1])

			if j <= n:
				V[j + 1, j] = (2 * j + 1) * z0 * V[j, j]
				W[j + 1, j] = (2 * j + 1) * z0 * W[j, j]

			for i in range(j + 2, n + 2):
				V[i, j] = ((2 * i - 1) * z0 * V[i - 1, j] - (i + j - 1) * rho * V[i - 2, j]) / (i - j)
				W[i, j] = ((2 * i - 1) * z0 * W[i - 1, j] - (i + j - 1) * rho * W[i - 2, j]) / (i - j)

		ax = 0
		ay = 0
		az = 0

		for j in range(0, m + 1):
			for i in range(j, n + 1):

				if j == 0:
					ax -= C[i, j] * V[i + 1, 1]
					ay -= C[i, j] * W[i + 1, 1]
					az -= (i + 1) * C[i, j] * V[i + 1, 0]
				else:
					Fac = 0.5 * (i - j + 1) * (i - j + 2)
					ax += 0.5 * (-C[i, j] * V[i + 1, j + 1] - S[i, j] * W[i + 1, j + 1]) + \
						  Fac * (C[i, j] * V[i + 1, j - 1] + S[i, j] * W[i + 1, j - 1])

					ay += 0.5 * (-C[i, j] * W[i + 1, j + 1] + S[i, j] * V[i + 1, j + 1]) + \
						  Fac * (-C[i, j] * W[i + 1, j - 1] + S[i, j] * V[i + 1, j - 1])

					az += ((i - j + 1) * (-C[i, j] * V[i + 1, j] - S[i, j] * W[i + 1, j]))

			ax = (mu / R_ref ** 2) * ax
			ay = (mu / R_ref ** 2) * ay
			az = (mu / R_ref ** 2) * az
			return np.array([ax, ay, az])

	def ydot(self, y, C, S, n, m, kepOrGeo, solar, solarEpsilon, sunAndMoon, drag, dragCoeff, draModel, satMass, goceDate, goceTime, currdatetime):
		"""Returns the time derivative of a given state.
			Args:
				y(1x6 numpy array): the state vector [rx,ry,rz,vx,vy,vz]
			Returns:
				1x6 numpy array: the time derivative of y [vx,vy,vz,ax,ay,az]
		"""

		mu = 398600.4405e+09
		r = np.linalg.norm(y[0:3])

		a = np.array([0.0, 0.0, 0.0])
		accelerationMoon = np.array([0.0, 0.0, 0.0])
		accelerationDrag = np.array([0.0, 0.0, 0.0])
		accelerationSun = np.array([0.0, 0.0, 0.0])
		accelerationRadiation = np.array([0.0, 0.0, 0.0])

		if kepOrGeo == 1:
			a = -mu/(r**3)*y[0:3]
		elif kepOrGeo == 2:
			a = self.geodynamic_model(y, C, S, n, m)

		self.accelerations[0, :] = a

		bspFileName = 'de430.bsp'
		try:
			currdatetime = currdatetime + datetime.timedelta(seconds=self.epochs[-1])
		except:
			pass

		positionSun, positionMoon = position_sun_moon(bspFileName, currdatetime)

		if sunAndMoon is True:
			accelerationSun, accelerationMoon = find_sun_moon_acc(y, positionSun, positionMoon)

		if solar is True:
			accelerationRadiation = get_solar_radiation_petrubation(positionSun, y[0:3], solarEpsilon, satMass, np.array([4.6, 2.34, 2.20]))

		if drag is True:
			if draModel == 1:
				accelerationDrag = find_drag_petrubation(dragCoeff, satMass, np.array([4.6, 2.34, 2.20]), y)
			elif draModel == 2:
				goceFileName = "goce_denswind_v1_5_2012-11.txt"
				accelerationDrag = doorbnos_drag(goceTime, goceDate, y, goceFileName, dragCoeff)

		a = a + accelerationSun + accelerationMoon + accelerationRadiation + accelerationDrag

		self.accelerations[1, :] = accelerationSun
		self.accelerations[2, :] = accelerationMoon
		self.accelerations[3, :] = accelerationRadiation
		self.accelerations[4, :] = accelerationDrag

		return np.array([*y[3:6], *a])

	def rk4(self, y, t0, tf, h, kepOrGeo, solar, solarEpsilon, sunAndMoon, drag, dragCoeff, draModel, C, S, satMass, goceDate, goceTime, currdatetime):
		"""Runge-Kutta 4th Order Numerical Integrator
			Args:
				y(1x6 numpy array): the state vector [rx,ry,rz,vx,vy,vz]
				t0(float)  : initial time
				tf(float)  : final time
				h(float)   : step-size
			Returns:
				1x6 numpy array: the state at time tf
		"""

		t = t0
		self.keepAccelerations = []
		self.keepStateVectors = []
		self.epochs = []
		keepGoceTime = goceTime

		if tf < t0:
			h = -h

		while(abs(tf-t) > 0.00001):
			if (abs(tf-t) < abs(h)):
				h = tf-t

			try:
				goceTimeObj = datetime.datetime.strptime(goceDate + " " + keepGoceTime, '%Y-%m-%d %H:%M:%S')
			except:
				goceTimeObj = datetime.datetime.strptime(goceDate + " " + keepGoceTime, '%Y-%m-%d %H:%M:%S.%f')
			stepTimeObj = datetime.timedelta(seconds=h)
			goceTime = str(goceTimeObj + stepTimeObj).split(" ")[1]
			keepGoceTime = goceTime
			goceTime = goceTime[:-1] + "0.000"

			k1 = h * self.ydot(y, C, S, self.n, self.m, kepOrGeo, solar, solarEpsilon, sunAndMoon, drag, dragCoeff, draModel, satMass, goceDate, goceTime, currdatetime)


			self.keepAccelerations.append(np.copy(self.accelerations))

			k2 = h * self.ydot(y + k1 / 2, C, S, self.n, self.m, kepOrGeo, solar, solarEpsilon, sunAndMoon, drag, dragCoeff, draModel, satMass, goceDate, goceTime, currdatetime)
			k3 = h * self.ydot(y + k2 / 2, C, S, self.n, self.m, kepOrGeo, solar, solarEpsilon, sunAndMoon, drag, dragCoeff, draModel, satMass, goceDate, goceTime, currdatetime)
			k4 = h * self.ydot(y + k3, C, S, self.n, self.m, kepOrGeo, solar, solarEpsilon, sunAndMoon, drag, dragCoeff, draModel, satMass, goceDate, goceTime, currdatetime)

			self.keepStateVectors.append(y)

			y = y+(k1+2*k2+2*k3+k4)/6

			self.epochs.append(t)
			#print(t)

			t = t+h

		return y

	def accelerations_graph(self, solar, sunAndMoon, drag):
		"""
		Create numpy arrays for keeping all the accelerations to be used
		for graphs in the main web_app.py. Also compute the number that
		represents the order of magnitude of every acceleration
		"""

		self.keepAbsoluteAccelerations = []
		self.keepWantedAcceleration = []
		self.keepWantedTickLabels = []
		wantedAcceleration = []
		keepMean = []
		for j in range(0, 5):
			for i in range(0, len(self.keepAccelerations)):
				wantedAcceleration.append(mp.sqrt(self.keepAccelerations[i][j, 0]**2 + self.keepAccelerations[i][j, 1]**2 + self.keepAccelerations[i][j, 2]**2))

			if wantedAcceleration[0] != 0:
				self.keepWantedAcceleration.append(wantedAcceleration)
				if j == 0:
					self.keepWantedTickLabels.append("Earth")
				elif j == 1:
					self.keepWantedTickLabels.append("Sun")
				elif j == 2:
					self.keepWantedTickLabels.append("Moon")
				elif j == 3:
					self.keepWantedTickLabels.append("Solar")
				elif j == 4:
					self.keepWantedTickLabels.append("Atmospheric")

			checkWith = np.mean(wantedAcceleration)
			self.keepAbsoluteAccelerations.append([np.max(wantedAcceleration), np.min(wantedAcceleration), checkWith, np.std(wantedAcceleration)])

			# Order of magnitude
			if checkWith > 1:
				if checkWith / 10 > 1:
					if checkWith / 100 > 1:
						finalwantedAcceleration = 3
					else:
						finalwantedAcceleration = 2
				else:
					finalwantedAcceleration = 1
			else:
				if checkWith * 10 < 1:
					if checkWith * 100 < 1:
						if checkWith * 1000 < 1:
							if checkWith * 10000 < 1:
								if checkWith * 100000 < 1:
									if checkWith * 1000000 < 1:
										if checkWith * 10000000 < 1:
											finalwantedAcceleration = -8
										else:
											finalwantedAcceleration = -7
									else:
										finalwantedAcceleration = -6
								else:
									finalwantedAcceleration = -5
							else:
								finalwantedAcceleration = -4
						else:
							finalwantedAcceleration = -3
					else:
						finalwantedAcceleration = -2
				else:
					finalwantedAcceleration = -1

			keepMean.append(finalwantedAcceleration)
			wantedAcceleration = []

		self.accelerationsGraph = keepMean

		self.tickLabels = []
		rowsToKeep = [0]
		self.tickLabels.append("Earth")
		if sunAndMoon == True:
			self.tickLabels.append("Sun")
			self.tickLabels.append("Moon")
			rowsToKeep.append(1)
			rowsToKeep.append(2)

		if solar == True:
			self.tickLabels.append("Radiation")
			rowsToKeep.append(3)

		if drag == True:
			self.tickLabels.append("Atmospheric")
			rowsToKeep.append(4)

		finalKeepAbsoluteAccelerations = np.zeros((len(self.tickLabels), 4))
		for i in range(0, len(rowsToKeep)):
			finalKeepAbsoluteAccelerations[i, :] = self.keepAbsoluteAccelerations[int(rowsToKeep[i])]

		self.keepAbsoluteAccelerations = np.copy(finalKeepAbsoluteAccelerations)

		finalAccelerationsGraph = np.zeros(len(self.tickLabels))
		for i in range(0, len(rowsToKeep)):
			finalAccelerationsGraph[i] = self.accelerationsGraph[int(rowsToKeep[i])]

		self.accelerationsGraph = np.copy(finalAccelerationsGraph)

	def earth_track_map(self, time0):
		"""
		deprecated for now 
		"""

		unpackStateVectors = np.asarray(self.keepStateVectors)

		# print(unpackStateVectors)
		y = np.mean(unpackStateVectors, 0)
		y = y / 1000
		kep = state_kep(y[0:3], y[3:6])

		a = kep[0]
		e = kep[1]
		inc = mp.radians(kep[2])
		t0 = mp.radians(kep[3])
		lan = mp.radians(kep[4])
		tanom = mp.radians(kep[5])

		p_x = np.array([mp.cos(lan), mp.sin(lan), 0])
		p_y = np.array([-mp.sin(lan) * mp.cos(inc), mp.cos(lan) * mp.cos(inc), mp.sin(inc)])

		# generate 2000 points on the ellipse
		theta = np.linspace(t0 + tanom, t0 + tanom + 4 * mp.pi, 2000)
		radii = a * (1 - e ** 2) / (1 + e * np.cos(theta - t0))

		# convert to cartesian
		x_s = np.multiply(radii, np.cos(theta))
		y_s = np.multiply(radii, np.sin(theta))

		# convert to 3D
		mat = np.column_stack((p_x, p_y))
		coords_3D = np.matmul(mat, [x_s, y_s])

		ecc = true_to_ecc(theta, e)
		mean = ecc_to_mean(ecc, e)
		times = mean_to_t(mean, a)
		times += time0

		coords_teme = np.column_stack((times, coords_3D[0], coords_3D[1], coords_3D[2]))
		coords_ecef = conv_to_ecef(coords_teme)

		return coords_ecef, times

	def keplerian_elements_graph(self):
		"""
		Create a statistics table/dataframe for keplerian elements
		to be used by web_app.py
		"""

		self.keepKepElements = np.array([])
		usableStateVector = np.asarray(self.keepStateVectors)
		keepKepElements = np.zeros((len(self.keepStateVectors), 6))
		for i in range(0, len(usableStateVector)):
			r = usableStateVector[i, 0:3] / 1000
			v = usableStateVector[i, 3:6] / 1000
			keepKepElements[i, :] = state_kep(r, v)[:]

		self.keepKepElements = keepKepElements
		keepStatisticKep = np.zeros((6, 4))
		keepStatisticKep[:, 0] = np.max(keepKepElements, axis=0)
		keepStatisticKep[:, 1] = np.min(keepKepElements, axis=0)
		keepStatisticKep[:, 2] = np.mean(keepKepElements, axis=0)
		keepStatisticKep[:, 3] = np.std(keepKepElements, axis=0)

		returnStatisticKepTable = pd.DataFrame(
			data=keepStatisticKep,
			index=["Semi Majox Axis(km)", "Eccentricity(float)", "Inclination(degrees)", "Argument of Perigee(degrees)", "Longitude of the ascending node(degrees)", "True anomaly(degrees)"],
			columns=["Max", "Min", "Average", "STD"]
		)
		returnStatisticKepTable.insert(0, "Keplerian Element", returnStatisticKepTable.index)

		return returnStatisticKepTable, keepKepElements

	def download_state_vectors(self):
		"""
		Method to download state vectors csv
		"""

		datestr = str(datetime.datetime.time(datetime.datetime.now())).replace(":", "")
		datestr = datestr.replace(".", "")
		filename = "state_" + datestr + ".csv"
		finalPrintArray = np.zeros((len(self.keepStateVectors), 7))
		finalPrintArray[:, 0] = self.epochs
		finalPrintArray[:, 1:] = np.asarray(self.keepStateVectors)[:, :]
		np.savetxt(filename, finalPrintArray, delimiter=",")

		returnStateTable = pd.DataFrame(
			data=finalPrintArray[:, 1:],
			index=finalPrintArray[:, 0],
			columns=["rx(m)", "ry(m)", "rz(m)", "vx(m/s)", "vy(m/s)", "vz(m/s)"]
		)

		returnStateTable.index.name = "Time(sec)"

		returnStateTable.to_csv(filename, sep=",")

	def download_kep_vectors(self):
		"""
		Method to download keplerian elements csv
		"""

		datestr = str(datetime.datetime.time(datetime.datetime.now())).replace(":", "")
		datestr = datestr.replace(".", "")
		filename = "kep_" + datestr + ".csv"
		finalPrintArray = np.zeros((len(self.keepKepElements), 7))
		finalPrintArray[:, 0] = self.epochs
		finalPrintArray[:, 1:] = np.asarray(self.keepKepElements)[:, :]
		# np.savetxt(filename, finalPrintArray, delimiter=",")

		returnKepTable = pd.DataFrame(
			data=finalPrintArray[:, 1:],
			index=finalPrintArray[:, 0],
			columns=["a(km)", "e(float)", "i(degrees)", "ω(degrees)", "Ω(degrees)", "v(degrees)"]
		)

		returnKepTable.index.name = "Time(sec)"

		returnKepTable.to_csv(filename, sep=",")

	def download_accel_vectors(self):
		"""
		Method to download accelerations vectors csv
		"""

		datestr = str(datetime.datetime.time(datetime.datetime.now())).replace(":", "")
		datestr = datestr.replace(".", "")
		filename = "accel_" + datestr + ".csv"
		finalPrintArray = np.zeros((len(self.epochs)*5, 4))

		for i in range(0, len(self.epochs)):
			for j in range(0, 5):
				finalPrintArray[i * 5 + j, 0] = self.epochs[i]
				finalPrintArray[i * 5 + j, 1:4] = np.asarray(self.keepAccelerations)[i][j, :]

		tempoTickLabels = ["Earth", "Sun", "Moon", "Radiation", "Atmospheric"]
		finalTickLabels = np.zeros((len(self.epochs) * 5, 1), dtype=object)
		for i in range(0, len(self.epochs)):
			for j in range(0, 5):
				finalTickLabels[i * 5 + j, 0] = tempoTickLabels[j]

		returnAcceTable = pd.DataFrame(
			data=finalPrintArray[:, 1:],
			index=finalPrintArray[:, 0],
			columns=["ax(m**2/s)", "ay(m**2/s)", "az(m**2/s)"]
		)

		returnAcceTable.index.name = "Time(sec)"
		returnAcceTable.insert(0, "Source", finalTickLabels[:])

		returnAcceTable.to_csv(filename, sep=",")


if __name__ == "__main__":

	y = np.array([4.57158479e+06, -5.42842773e+06, 1.49451936e+04, -2.11034321e+02, -1.61886788e+02, 7.48942330e+03])
	t0, tf = 0, 20000.00
	final = np.zeros((200, 6))
	final_2 = np.zeros((200, 6))
	diffs = []

	# propagatorObj = propagator()
	# # propagatorObj.restruct_geopotential_file("RWI_TOPO_2012_plusGRS80.gfc")
	# data = propagatorObj.read_geopotential_coeffs("restruct_EGM2008.gfc", False)
	# propagatorObj.createNumpyArrayForCoeffs(data, 3, 2)
	#
	# for i in range(0, 1):
	# 	final[i, :] = propagatorObj.rk4(y, t0, tf, 100, 2, False, 0.5, False, False, 2.1, 1, propagatorObj.C,
	# 									propagatorObj.S, 720, "2012-11-20", "17:40:00", datetime.datetime.now())

	for j in range(5, 20):
		propagatorObj = propagator()
		data = propagatorObj.read_geopotential_coeffs("restruct_EGM2008.gfc", False)
		propagatorObj.createNumpyArrayForCoeffs(data, j, j)

		print(np.size(propagatorObj.C))

		final[0, :] = propagatorObj.rk4(y, t0, tf, 100, 2, False, 0.5, False, False, 2.1, 1, propagatorObj.C, propagatorObj.S, 720, "2012-11-20", "17:40:00", datetime.datetime.now())

		final[:, :] = np.asarray(propagatorObj.keepStateVectors)[:, :]

		propagatorObj = propagator()
		data = propagatorObj.read_geopotential_coeffs("restruct_EGM2008.gfc", False)
		propagatorObj.createNumpyArrayForCoeffs(data, j+1, j+1)

		print(np.size(propagatorObj.C))

		final_2[0, :] = propagatorObj.rk4(y, t0, tf, 100, 2, False, 0.5, False, False, 2.1, 1, propagatorObj.C,
										   propagatorObj.S, 720, "2012-11-20", "17:40:00", datetime.datetime.now())

		final_2[:, :] = np.asarray(propagatorObj.keepStateVectors)[:, :]

		diffs.append(final_2[:, :] - final[:, :])

	# print(diffs[0][0,:])
		print(np.mean(diffs[j-5], axis=0))