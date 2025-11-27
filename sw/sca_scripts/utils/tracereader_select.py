import data_formats.dat_tracereader as dat_tracereader
import data_formats.hdf5_tracereader as hdf5_tracereader


# function autoselecting the appropriate tracereader class according to the
# extension given a pathname will open the corresponding tracefile
# returns the tracereader object and the file prefix
# TODO: add option for read-only opening
def autoselect_reader(pathname):
   split_filename = pathname.split('.')
   if ( (split_filename[-1] == "hdf5") or 
        (split_filename[-1] == "h5")):
       tracefile = hdf5_tracereader.hdf5_tracereader()
   else:
       tracefile = dat_tracereader.dat_tracereader() 
   tracefile.open(pathname)
   return tracefile,[ pathname[:-( len(split_filename[-1])+1)] , split_filename[-1] ]

