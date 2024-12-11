### temperal line prediction function
import numpy as np
#import glob
import tensorflow as tf
import tqdm
import dill as pickle
from . import cont_pca
from .cont_pca import SpectrumPCA
from .nn import Speculator
from .utils import cont_lam, logQ
#import __main__
#__main__.SpectrumPCA = SpectrumPCA

### read the fit PCAs and NN
try:
    from pkg_resources import resource_filename, resource_listdir
except(ImportError):
    pass
#import runpy
#runpy._run_module_as_main("cont_pca.SpectrumPCA")
#runpy.run_path(resource_filename("cue","cont_pca.py"), {}, "__main__")
with open(resource_filename("cue", "data/pca_cont_new.pkl"), 'rb') as f:
    cont_PCABasis = pickle.load(f)
cont_speculator = Speculator(restore = True, 
                             restore_filename = resource_filename("cue", "data/speculator_cont_new"))

#par = pd.DataFrame(data={'num':par[:,0], 'index1':par[:,2], 'index2':par[:,3], 'index3':par[:,4], 'index4':par[:,5], 
#                         'delta_logL1':par[:,6], 'delta_logL2':par[:,7], 'delta_logL3':par[:,8],
#                         'logU':par[:,9], 'Rinner':par[:,10], 'logQ':par[:,11], 'nH':par[:,12],
#                         'efrac':par[:,13], 'gas_logZ':par[:,14], 'NO':par[:,15], 'CO':par[:,16]
#                         })

class predict():
    """
    Nebular Continuum Emission Prediction
    :param theta: nebular parameters of n samples, (n, 12) matrix 
    :param gammas, log_L_ratios, log_QH, n_H, log_OH_ratio, log_NO_ratio, log_CO_ratio: 12 input parameters, vectors
    :param wavelength: wavelengths corresponding to the neural net output luminosities
    :output sorted wavelength, and L_nu in erg/Hz sorted by wavelength
    """
    
    def __init__(self, pca_basis=cont_PCABasis, nn=cont_speculator, theta=None, gammas=None, log_L_ratios=None, log_QH=None, 
                 n_H=None, log_OH_ratio=None, log_NO_ratio=None, log_CO_ratio=None, 
                 wavelength=cont_lam[122:],  
                 #wav_selection = None,
                 #parameter_selection = None
                ):
        """
        Constructor.
        """        
        # input parameters
        self.pca_basis = pca_basis
        self.nn = nn
        self.n_segments = np.size(nn)
        self.wavelength = np.array(wavelength)
        if theta is None:
            if (np.size(log_QH)==1):
                self.n_sample = 1
                self.theta = np.hstack([gammas, log_L_ratios, log_QH, n_H, 
                                        log_OH_ratio, log_NO_ratio, log_CO_ratio]).reshape((1, 12))
            else:
                self.n_sample = len(log_QH)
                self.gammas = np.array(gammas)
                self.log_L_ratios = np.array(log_L_ratios)
                self.log_QH = np.reshape(log_QH, (len(log_QH), 1))
                self.n_H = np.reshape(n_H, (len(n_H), 1))
                self.log_OH_ratio = np.reshape(log_OH_ratio, (len(log_OH_ratio), 1))
                self.log_NO_ratio = np.reshape(log_NO_ratio, (len(log_NO_ratio), 1))
                self.log_CO_ratio = np.reshape(log_CO_ratio, (len(log_CO_ratio), 1))
                self.theta = np.hstack([self.gammas, self.log_L_ratios, self.log_QH, self.n_H, 
                                        self.log_OH_ratio, self.log_NO_ratio, self.log_CO_ratio])
        else:
            self.theta = tf.convert_to_tensor(theta, dtype=tf.float32)
            self.n_sample = tf.shape(self.theta)[0]
            #self.theta[:,-2:] = 10**self.theta[:,-2:]
        #raise ValueError('NEBULAR PARAMETER ERROR: input {0} parameters but required 12'.format(len(theta[0]))
    
    def nn_predict(self):
        # shift and scale
        wavind_sorted = tf.argsort(self.wavelength)
        fit_spectra = []

        if self.n_segments == 1:
            log_spectrum = self.nn.log_spectrum_(self.theta)
            fit_spectra = self.pca_basis.PCA.inverse_transform(log_spectrum) * self.nn.log_spectrum_scale_ + self.nn.log_spectrum_shift_
            if self.n_sample == 1:
                fit_spectra = tf.squeeze(fit_spectra)[wavind_sorted]
            else:
                fit_spectra = tf.gather(tf.squeeze(fit_spectra), wavind_sorted, axis=1)
            self.nn_spectra = fit_spectra
        else:
            this_spec = []
            for j in range(self.n_segments):
                log_spectrum = self.nn[j].log_spectrum_(self.theta)
                segment_spectrum = self.pca_basis[j].PCA.inverse_transform(log_spectrum) * self.nn[j].log_spectrum_scale_ + self.nn[j].log_spectrum_shift_
                this_spec.append(segment_spectrum)
            fit_spectra.append(tf.gather(tf.concat(this_spec, axis=1), wavind_sorted, axis=1))
            self.nn_spectra = tf.squeeze(tf.stack(fit_spectra))

        self.wavelength = tf.gather(self.wavelength, wavind_sorted)
        return self.wavelength, tf.pow(10.0, self.nn_spectra)


def get_cont(par):
    """
    A wrapper of nebular continuum emulator for SED fitting.
    """
    neb_cont = cont_predict(gammas=[par['ionspec_index1'], par['ionspec_index2'], 
                                    par['ionspec_index3'], par['ionspec_index4']],
                            log_L_ratios=[par['ionspec_logLratio1'], par['ionspec_logLratio2'],
                                          par['ionspec_logLratio3']],
                            log_QH=logQ(par['gas_logu'], lognH=par['gas_logn']),
                            n_H=10**par['gas_logn'],
                            log_OH_ratio=par['gas_logz'],
                            log_NO_ratio=par['gas_logno'],
                            log_CO_ratio=par['gas_logco'],
                           ).nn_predict()
    cont_spec = neb_cont[1]/3.839E33/10**logQ(par['gas_logu'], lognH=par['gas_logn'])*10**par['log_qion'] # convert to the unit in FSPS
    from scipy.interpolate import CubicSpline
    neb_cont_cs = CubicSpline(neb_cont[0], cont_spec, extrapolate=True) # interpolate onto the fsps wavelengths
    return {"normalized nebular continuum": cont_spec, "interpolator": neb_cont_cs}
    
    
#testing_spectra, testing_pca, testing_spectra_in_pca_basis = PCABasis.validate_pca_basis(spectrum_filename = contfiles[i])
#log_spectra = np.load(contfiles[i])
#log_spectra[log_spectra == 0] = 1e-37
#log_spectra = np.log10(log_spectra[:,122:])
#testing_pca.append(PCABasis.PCA.transform((log_spectra - PCABasis.log_spectrum_shift)/PCABasis.log_spectrum_scale))
