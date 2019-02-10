# figuring out what the best opening angle cut should be for Gamma and Pi0

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import glob
import h5py as h5
import numpy as np
from scipy.stats import binned_statistic

pi0_path = "/u/sciteam/zhang10/Projects/DNNCalorimeter/Data/NewSamples/Fixed/Pi0Escan_*_MERGED/Pi0Escan_*.h5"

###########
# COMBINE #
###########

pi0_files = glob.glob(pi0_path)

pi0_opening_angle = []
pi0_E = []

for file_name in pi0_files:
    file = h5.File(file_name, 'r')
    pi0_opening_angle += list(file['openingAngle'][:])
    pi0_E += list(file['energy'][:])
    file.close()

bins=np.arange(0,0.1,0.002)
plt.hist(np.clip(pi0_opening_angle, bins[0], bins[-1]), bins=bins, density=True, histtype='step', linewidth=1, label='Pi0')
plt.title('Opening Angle of Pi0 Events with Overflow Bin')
plt.xlabel('Opening Angle (Radians)')
plt.ylabel('Normalized Fraction')
plt.savefig('zoom_opening_angles.png')

plt.clf()

bin_pi0_E_means = binned_statistic(pi0_opening_angle, pi0_E, bins=20, range=(0, 0.2)).statistic

plt.plot(np.arange(0,0.2,0.01), bin_pi0_E_means, label='Pi0')
plt.title('Mean Pi0 Energy in Opening Angle Bins')
plt.xlabel('Opening Angle (Radians)')
plt.ylabel('Energy (GeV)')
plt.grid()
plt.savefig('mean_energy_vs_opening_angle.png')

plt.clf()

pi0_pass_cut = [a < 0.01 for a in pi0_opening_angle]
bin_pi0_pass_cut_means = binned_statistic(pi0_E, pi0_pass_cut, bins=50, range=(0, 500)).statistic

plt.plot(np.arange(0,500,10), bin_pi0_pass_cut_means, label='Pi0')
plt.title('Fraction of Pi0 Events Passing Opening Angle < 0.01 Cut')
plt.xlabel('Energy (GeV)')
plt.ylabel('Fraction')
plt.savefig('opening_angle_cut_vs_energy.png')