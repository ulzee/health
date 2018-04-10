from __future__ import print_function
from ljpeg import ljpeg
import numpy as np
import json, sys, os

import time
from shutil import copyfile
import cv2

from scipy.stats import multivariate_normal
import scipy.ndimage.filters as fi
import cPickle as pkl
import h5py

def canvas(img):
	if img.shape[1] > img.shape[0]:
		img = img[:, :img.shape[0]]
	filled = np.zeros((img.shape[0], img.shape[0]))
	filled[:img.shape[0], :img.shape[1]] = img[:, :img.shape[0]]
	filled[:, img.shape[1]:] = img[img.shape[0]/2, -1]
	return filled

def direction(img):
	hf = len(img[0]) / 2
	leftsample = np.sum(img[:, :hf] < 0.05)
	rightsample = np.sum(img[:, hf:] < 0.05)

	return 'right' if leftsample > rightsample else 'left'

def trim(img, xoff=0.02, yoff=0.1):
	hh, ww = img.shape
	x0 = int(ww * xoff)
	xf = int(ww * (1 - xoff))
	y0 = int(hh * yoff)
	yf = int(hh * (1 - yoff))
	return img[y0:yf, x0:xf]

def applyMark(img, markup, keepmask=None, oclist=[]):
	out = img.copy()
	path = json.loads(markup['trace'])
	x, y = markup['start']
	linecolor = (0,255,255)
	cv2.circle(out, (x, y), 3, linecolor, 4)
	cv2.circle(out, (x, y), 20, linecolor, 4)
	minmax = [1000000, 0, 1000000, 0] # xminmax, yminmax

	coords = [(y, x)]
	for dy, dx in path:
		x += dx
		y += dy
		minmax[0] = min(x, minmax[0])
		minmax[1] = max(x, minmax[1])
		minmax[2] = min(y, minmax[2])
		minmax[3] = max(y, minmax[3])
		cv2.circle(out, (x, y), 3, linecolor, 4)
		coords.append((y, x))

	coords = sorted(coords, key=lambda pos: pos[0]*100000+pos[1])
	# ys, xs = zip(*json.loads(markup['trace']))
	xmin, xmax, ymin, ymax = minmax
	xavg, yavg = (xmax + xmin) / 2, (ymax + ymin) / 2
	xrad, yrad = np.abs((xmax - xmin) / 2.0), np.abs((ymax - ymin) / 2.0)
	radius = int(max(xrad, yrad))
	diameter = radius * 2
	# bigdia = diameter * 2
	cv2.circle(out, (int(xavg), int(yavg)), radius, linecolor, 4)
	cv2.circle(out, (int(xavg), int(yavg)), 5, linecolor, 4)

	# print('RADIUS', radius)
	domain1d = np.linspace(0, 5, diameter)
	# kern1d = multivariate_normal.pdf(domain1d, mean=2.5, cov=0.5)
	# kbuffer =
	kmean = 2.5
	kern1d = multivariate_normal.pdf(domain1d, mean=kmean, cov=kmean / 5.0)
	kernel = np.outer(kern1d, kern1d)


	if keepmask is None:
		mask = np.zeros(img.shape)
	else:
		mask = keepmask
	# mask[ymin-radius:ymin+(2 + 1) * radius, xmin-radius:xmin+(2 + 1) * radius] = kernel
	# print(img.shape, kernel.shape, diameter)
	fity, fitx = mask[ymin:ymin+diameter, xmin:xmin+diameter].shape
	kernh, kernw = kernel[:fity, :fitx].shape

	def isInside(box, point):
		(px0, py0), (pxf, pyf) = box
		xx, yy = point
		return px0 <= xx and xx <= pxf and py0 <= yy and yy <= pyf

	is_occluded = False
	testPoints = [(xmin, ymin), (xmin+kernw, ymin), (xmin, ymin+kernh), (xmin+kernw, ymin+kernh)]
	for prevBox in oclist:
		for pnt in testPoints:
			if isInside(prevBox, pnt):
				is_occluded = True

	lasty = coords[0][0]
	lastind = 0
	for ii, (yy, xx) in enumerate(coords):
		if yy == lasty:
			continue
		x0 = coords[lastind][1]
		xf = coords[ii - 1][1]
		mask[lasty, x0:xf] = 1
		lasty = yy
		lastind = ii

	# if not is_occluded:
	# 	kernel *= 1.0 / np.max(kernel)
	# 	mask[ymin:ymin+diameter, xmin:xmin+diameter] = kernel[:fity, :fitx]
	# 	oclist.append([(xmin, ymin), (xmin+kernw, ymin+kernh)])

	assert mask is not None

	return out, mask, oclist, coords

def bbox(img, size=2048, lowcut = 255 * 0.05):
	maxy = 0
	ypos = 0
	for yy in range(len(img) - 1, 0, -1):
		miny = 0
		for xx in range(len(img[yy])):
			if img[yy, xx] < lowcut:
				miny = xx
				break
		if maxy < miny:
			maxy = miny
			ypos = yy

	x0 = maxy - size
	if x0 < 0: x0 = 0
	y0 = ypos - size / 2
	if y0 < 0: y0 = 0
	if y0 + size >= len(img): y0 -= (y0 + size - len(img))

	return x0, y0, x0 + size, y0 + size

def DBA_MGH(mat):
	mat[mat < 1] = 1
	# mat[mat > 55722] = 55722
	return (np.log10(mat) - 4.80662) / -1.07553

def HOWTEK_MGH(mat):
	return (3.789 - 0.00094568 * mat)

def LUMISYS_WFU(mat):
	return ( mat - 4096.99 ) / -1009.01

def HOWTEK_ISMD(mat):
	return (3.96604095240593 + (-0.00099055807612) * (mat))

# DATAROOT = 'data'
DATAROOT = '/media/ul1994/ssd1tb'

def datapath(case, sequence):
	return '%s/phenotype-tiles/%s/%s' % (DATAROOT, case['diagnosis'], sequence['name'])

def pngpath(case, sequence):
	return '%s/phenotype-tiles/%s/%s.png' % (DATAROOT, case['diagnosis'], sequence['name'])

def maskpath(case, sequence):
	return '%s/phenotype-tiles/%s/%s-mask.npy' % (DATAROOT, case['diagnosis'], sequence['name'])

def preview_maskpath(case, sequence):
	return '%s/phenotype-tiles/%s/%s-mask.png' % (DATAROOT, case['diagnosis'], sequence['name'])

def markedpath(case, sequence):
	return '%s/phenotype-tiles/%s/%s-marked.png' % (DATAROOT, case['diagnosis'], sequence['name'])

def thumbpath(case, sequence):
	return '%s/phenotype-tiles/%s/%s-thumb.png' % (DATAROOT, case['diagnosis'], sequence['name'])

import matplotlib.pyplot as plt
import scipy.misc
import cv2
import random
import PIL

# DEBUGONE = 'A-1010-1'
# DEBUGANGLE = 'RIGHT_CC'

DEBUGONE = None
DEBUGANGLE = None

def imrotate(img, ang):
	img = PIL.Image.fromarray(img)
	img = img.rotate(ang)
	img = np.array(img)
	return img

def dump_cancer_samples(ph, sc, density, mask, coords, size=256, facing='left'):
	RANDROT = 30 # +- 15 degrees
	ROTBUFFER = 50
	pname = '%s/phenotype-tiles/%s/%s' % (DATAROOT, ph['diagnosis'], sc['name'])
	# bsize = len(density) / (size * 2)
	hs = size / 2 + ROTBUFFER
	hs0 = size / 2

	density_data = np.zeros((16, size, size), dtype=np.float32)
	mask_data = np.zeros((16, size, size), dtype=np.uint8)
	for ii in range(16):
		ridx = random.randint(0, len(coords) - 1)
		angle = random.randint(-RANDROT, RANDROT)
		yy, xx = coords[ridx]
		sample = density[yy-hs:yy+hs,xx-hs:xx+hs]
		sample_mask = mask[yy-hs:yy+hs,xx-hs:xx+hs]
		sample = imrotate(sample, angle)
		sample = sample[ROTBUFFER:-ROTBUFFER,ROTBUFFER:-ROTBUFFER]
		sample_mask = imrotate(sample_mask, angle)
		sample_mask = sample_mask[ROTBUFFER:-ROTBUFFER,ROTBUFFER:-ROTBUFFER]
		if facing == 'right':
			sample = cv2.flip(sample, 1)
			sample_mask = cv2.flip(sample_mask, 1)
		density_data[ii] = sample
		mask_data[ii] = sample_mask
		# bname = pname + ('-sample-%d' % (ii))
		# pkl.dump(sample, open(bname + '.pkl', 'wb'))
		# pkl.dump(sample_mask.astype(np.uint8), open(bname + '-mask.pkl', 'wb'))
		# np.save(bname + '.npy', sample)
		# np.save(bname + '-mask.npy', sample_mask.astype(np.uint8))
	with h5py.File(pname + '-samples.h5', "w") as fl:
		fl.create_dataset('density', data=density_data, compression='gzip')
		fl.create_dataset('mask', data=mask_data, compression='gzip')
		# mask_db.close()

def dump_tiles(ph, sc, density, mask, marked, size=512):
	pname = '%s/phenotype-tiles/%s/%s' % (DATAROOT, ph['diagnosis'], sc['name'])
	bsize = len(density) / size
	inds = []
	for byy in range(bsize):
		for bxx in range(bsize):
			inds.append((byy, bxx))
	random.shuffle(inds)
	inds = inds[:16]

	density_data = np.zeros((16, size, size), dtype=np.float32)
	mask_data = np.zeros((16, size, size), dtype=np.uint8)
	for ii, (byy, bxx) in enumerate(inds):
		bname = pname + ('-%dx%d' % (byy, bxx))
		y0 = byy * size
		yf = (byy + 1) * size
		x0 = bxx * size
		xf = (bxx + 1) * size
		# print(y0, yf, x0, xf)
		if mask is not None:
			mask_data[ii] = mask[y0:yf, x0:xf].astype(np.uint8)
			# np.save(bname + '-mask.npy', mask[y0:yf, x0:xf].astype(np.uint8))
			# scipy.misc.imsave(markedpath(ph, sc), marked[y0:yf, x0:xf])
		density_data[ii] = density[y0:yf, x0:xf].astype(np.float32)
		# np.save(bname + '.npy', density[y0:yf, x0:xf].astype(np.float32))
	with h5py.File(pname + '-random.h5', "w") as fl:
		fl.create_dataset('density', data=density_data, compression='gzip')
		fl.create_dataset('mask', data=mask_data, compression='gzip')

def dump(ph, sc, density, mask, marked, size=256):
	scale = 256 / float(len(final_mask))
	if mask is not None:
		mask = cv2.resize(mask, (0, 0), fx=scale, fy=scale)
		np.save(maskpath(ph, sc), mask.astype(np.uint8))
		marked = cv2.resize(marked, (0, 0), fx=scale, fy=scale)
		scipy.misc.imsave(markedpath(ph, sc), marked)
	density = cv2.resize(density, (0, 0), fx=scale, fy=scale)
	np.save(datapath(ph, sc), density)

if __name__ == '__main__':
	with open('metadata.json') as fl:
		metadata = json.load(fl)

	if len(sys.argv) == 1: raise Exception('Specify label')

	labels = [
		'cancers',
		'benigns',
		'callbacks',
		'normals',
	]

	lid = int(sys.argv[1])
	angle = sys.argv[2]
	skip = int(sys.argv[3])
	label = labels[lid]

	chosen = [elem for elem in metadata.values() if elem['diagnosis'] == label]

	print('Parsing:', label, len(chosen))

	plt.ion()
	for ii, elem in enumerate(chosen):
		elem['root'] = elem['root'].replace('ssd1tb1', 'ssd1tb')
		t0 = time.time()
		try:
			assert len(elem['scans']) == 4
		except:
			print(elem['root'])
			print(elem['scans'])
			raise Exception('Few scans... %d' % (len(elem['scans'])))
		if DEBUGONE and elem['name'] != DEBUGONE:
			continue
		if ii < skip: continue

		available_scans = elem['scans'].values()
		if DEBUGANGLE:
			available_scans =[elem['scans'][DEBUGANGLE]]
		for scaninfo in available_scans:
			if angle not in scaninfo['name']: continue
			has_details = 'details' in scaninfo
			if has_details:
				try:
					assert len(scaninfo['details']['markups']) != 0
				except:
					print(scaninfo)
					raise Exception('Missing markups!')
			scanfile = '%s/%s.LJPEG' % (elem['root'], scaninfo['name'])
			# print(scanfile)
			# tmpfile = 'tmp-%d.LJPEG' % lid
			# try:
			# 	copyfile(scanfile, tmpfile)
			# except:
			# 	print('Could not find files:', scanfile)
			try:
				# scan = ljpeg.read(tmpfile).astype(np.float)
				scan = ljpeg.read(scanfile).astype(np.float)
			except:
				print('READ ERROR:', scaninfo['name'], elem['root'])
				continue
			scan = scan.reshape((max(scan.shape), min(scan.shape)))
			# print('RAW   :', np.min(scan), np.max(scan))
			# scipy.misc.imsave('sample-raw.png', scan / 4095.0 * 255.0) # dump
			hh, ww = scan.shape
			calibrated = None
			exec('calibrated = %s(scan)' % elem['digitizer'].replace('-', '_'))
			maxod = 3.6
			calibrated = maxod - calibrated
			rawod = calibrated.copy()

			cliplow = maxod / 4.0
			calibrated -= cliplow
			calibrated /= (maxod - cliplow)
			calibrated[calibrated < 0] = 0
			calibrated[calibrated > 1] = 1
			grayscale = (255 * calibrated).astype(np.uint8)

			visible = calibrated - 0.3333
			visible /= 0.66666
			visible[visible < 0] = 0
			visible[visible > 1] = 1
			visible = (255 * visible).astype(np.uint8)

			# cleanup
			trimmed = trim(grayscale)
			facing = direction(trimmed)
			trimmed_visible = trim(visible)
			trimmed_od = trim(rawod)
			if facing == 'right':
				trimmed = cv2.flip(trimmed, 1)
				trimmed_visible = cv2.flip(trimmed_visible, 1)
				trimmed_od = cv2.flip(trimmed_od, 1)
			filled = canvas(trimmed)
			filled_visible = canvas(trimmed_visible)
			filled_od = canvas(trimmed_od)
			x0, y0, xf, yf = bbox(filled)
			boxedim = filled_visible[y0:yf, x0:xf]

			phenotype = { 'diagnosis': 'normals' }

			xsmall = 512 / float(filled.shape[1])
			ysmall = 512 / float(filled.shape[0])
			cropzone = filled_visible.copy()
			cv2.rectangle(cropzone, (x0,y0), (xf, yf), 0, 10)


			outmask_preview = None
			outmask = None
			outmarked = None
			if has_details:
				phenotype = { 'diagnosis': 'benigns' }
				if elem['diagnosis'] == 'cancers':
					phenotype = { 'diagnosis': 'cancers' }
				# print('MARKS:', len(scaninfo['details']['markups']))
				mask = None
				markedim = grayscale.copy()
				# try:
				occlusion_list = []
				coords_list = []
				oclist = occlusion_list
				for jj, markup in enumerate(scaninfo['details']['markups']):
					markedim, mask, oclist, coords = applyMark(markedim, markup, keepmask=mask, oclist=oclist)
					coords_list += coords

				dump_cancer_samples(phenotype, scaninfo, rawod, mask, coords_list, size=256, facing=facing)

				assert mask is not None
				trimmed_mask = trim(mask)
				trimmed_marked = trim(markedim)
				if facing == 'right':
					trimmed_mask = cv2.flip(trimmed_mask, 1)
					trimmed_marked = cv2.flip(trimmed_marked, 1)
				filled_mask = canvas(trimmed_mask)
				filled_marked = canvas(trimmed_marked)
				final_mask = filled_mask[y0:yf, x0:xf]
				if np.max(final_mask) < 0.25:
					# cancer is outside the inspection region and not visible
					# as far as phenotype is concerned, it is in normals...
					phenotype = { 'diagnosis': 'normals' }

				# scipy.misc.imsave(preview_maskpath(phenotype, scaninfo), )
				# np.save(maskpath(phenotype, scaninfo), final_mask)
				# scipy.misc.imsave(markedpath(phenotype, scaninfo), )
				# outmask_preview = 255.0 * final_mask
				# outmask = final_mask
				# scale256 = 256 / float(len(final_mask))
				# outmask = cv2.resize(final_mask, (0, 0), fx=scale256, fy=scale256)
				outmask = final_mask
				outmarked = 255.0 * filled_marked[y0:yf, x0:xf]

				if len(scaninfo['details']['markups']) > 1:
					print()
					print('Markups:', elem['name'], scaninfo['name'], len(scaninfo['details']['markups']))

			filled_od = filled_od[y0:yf, x0:xf]
			# scale256 = 256 / float(len(filled_od))
			# filled_od = cv2.resize(filled_od, (0, 0), fx=scale256, fy=scale256)
			# thumb_density = cv2.resize(cropzone, (0,0), fx=xsmall, fy=ysmall)
			# scipy.misc.imsave(pngpath(phenotype, scaninfo), boxedim)
			# scipy.misc.imsave(thumbpath(phenotype, scaninfo), )

			dump_tiles(phenotype, scaninfo, filled_od, outmask, outmarked, size=256)
			dump(phenotype, scaninfo, filled_od, outmask, outmarked, size=256)
			# if outmask is not None:

		dt = time.time() - t0
		sys.stdout.write('%d: %.2f (eta: %.2f)\r' % (ii, dt, dt * (len(chosen) - ii - 1) / 3600.0))
		sys.stdout.flush()

		break