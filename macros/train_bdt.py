import numpy as np
import matplotlib
matplotlib.use('Agg')
from argparse import ArgumentParser
from cmsjson import CMSJson
from pdb import set_trace

parser = ArgumentParser()
parser.add_argument(
   'what'
)
parser.add_argument(
   '--test', action='store_true'
)
parser.add_argument(
   '--jobtag', default='', type=str
)
parser.add_argument(
   '--ntrees', default=5000, type=int
)
parser.add_argument(
   '--depth', default=4, type=int
)
parser.add_argument(
   '--lrate', default=0.1, type=float
)
parser.add_argument(
   '--rstate', default=42, type=int
)
parser.add_argument(
   '--gamma', default=0, type=float
)
parser.add_argument(
   '--min_child_weight', default=1, type=int
)
parser.add_argument(
   '--subsample', default=1, type=float
)
parser.add_argument(
   '--colsample_bytree', default=1, type=float
)
parser.add_argument(
   '--reg_alpha', default=0, type=float
)
parser.add_argument(
   '--reg_lambda', default=1, type=float
)
parser.add_argument(
   '--nthreads', default=8, type=int
)
parser.add_argument(
   '--no_early_stop', action='store_true'
)
parser.add_argument(
   '--config'
)
parser.add_argument(
   '--dataset'
)
parser.add_argument(
   '--selection'
)
parser.add_argument(
   '--as_weight'
)
parser.add_argument(
   '--noweight', action='store_true'
)
parser.add_argument(
   '--SW94X', action='store_true'
)
parser.add_argument(
   '--usenomatch', action='store_true'
)
parser.add_argument(
   '--load_model', action='store_true'
)

args = parser.parse_args()

import json
if args.config:
   #config overrides eveything
   cfg = json.load(open(args.config))
   args.reg_alpha = cfg['reg_alpha'] 
   args.colsample_bytree = cfg['colsample_bytree'] 
   args.lrate = cfg['learning_rate'] 
   args.min_child_weight = cfg['min_child_weight'] 
   args.ntrees = cfg['n_estimators'] 
   args.subsample = cfg['subsample'] 
   args.reg_lambda = cfg['reg_lambda'] 
   args.depth = cfg['max_depth'] 
   args.gamma = cfg['gamma']

import matplotlib.pyplot as plt
import ROOT
import uproot
import rootpy
import pandas as pd
from matplotlib import rc
rc('font',**{'family':'sans-serif','sans-serif':['Helvetica']})
rc('text', usetex=True)
from datasets import tag, pre_process_data, target_dataset, get_models_dir, train_test_split
import os

dataset = 'test' if args.test else target_dataset
if args.dataset:
   dataset = args.dataset

mods = '%s/bdt_%s' % (get_models_dir(), args.what)
if not os.path.isdir(mods):
   os.makedirs(mods)

plots = '%s/src/LowPtElectrons/LowPtElectrons/macros/plots/%s/' % (os.environ['CMSSW_BASE'], tag)
if not os.path.isdir(plots):
   os.makedirs(plots)

from features import *
features, additional = get_features(args.what)

fields = features+labeling
if args.SW94X and 'seeding' in args.what:
   fields += seed_94X_additional
else:
   fields += additional

if 'gsf_pt' not in fields : fields += ['gsf_pt']

if not args.load_model :# dataset.endswith('.hdf'):
   data = pre_process_data(
      dataset, fields, 
      for_seeding=('seeding' in args.what),
      keep_nonmatch=args.usenomatch
      )
   if args.selection:
      data = data.query(args.selection)

   if args.as_weight:
      data['weight'] = data[args.as_weight]

   if args.noweight:
      data['weight'] = 1
   train_test, validation = train_test_split(data, 10, 8)
   train, test = train_test_split(train_test, 10, 6)
   validation.to_hdf(
      '%s/bdt_%s_testdata.hdf' % (mods, args.what),
      'data'
      ) 
   train.to_hdf(
      '%s/bdt_%s_traindata.hdf' % (mods, args.what),
      'data'
      ) 
   test.to_hdf(
      '%s/bdt_%s_valdata.hdf' % (mods, args.what),
      'data'
      ) 
else:   
   train = pd.read_hdf('%s/bdt_%s_traindata.hdf' % (mods, args.what), 'data')
   test = pd.read_hdf('%s/bdt_%s_valdata.hdf' % (mods, args.what), 'data')
   validation = pd.read_hdf('%s/bdt_%s_testdata.hdf' % (mods, args.what), 'data')
   if args.selection:
      train = train.query(args.selection)
      test  = test.query(args.selection)
      validation = validation.query(args.selection)

   if args.as_weight:
      train['weight'] = train[args.as_weight]
      test['weight'] = test[args.as_weight]
      validation['weight'] = validation[args.as_weight]
   if args.noweight:
      train['weight'] = 1
      test['weight'] = 1
      validation['weight'] = 1
   dataset = os.path.basename(dataset).split('.')[0]

from sklearn.externals import joblib
import xgboost as xgb
#
# Train BDTs
#

clf = None
if not args.load_model :

   print 'Training'
   print 'Input features:\n',features

   clf = xgb.XGBClassifier(
      #basic stuff
      max_depth=args.depth, learning_rate=args.lrate, n_estimators=args.ntrees,
      objective='binary:logitraw',
      #many different ways of regularization
      gamma=args.gamma, min_child_weight=args.min_child_weight, max_delta_step=0, 
      colsample_bytree=args.colsample_bytree, colsample_bylevel=1, subsample=args.subsample,
      reg_alpha=args.reg_alpha, reg_lambda=args.reg_lambda, 
      #running settings and weight balancing
      silent=False, nthread=args.nthreads, scale_pos_weight=1, 
   )
   
   early_stop_kwargs = {
      'eval_set' : [(test[features].as_matrix(), test.is_e.as_matrix().astype(int))],
      #'sample_weight_eval_set' : [test.weight.as_matrix()], #undefined in this version
      'eval_metric' : 'auc',
      'early_stopping_rounds' : 10
   } if not args.no_early_stop else {}

   clf.fit(
      train[features].as_matrix(), 
      train.is_e.as_matrix().astype(int), 
      sample_weight=train.weight.as_matrix(),
      **early_stop_kwargs
   )

   full_model = '%s/%s_%s_%s_BDT.pkl' % (mods, dataset, args.jobtag, args.what)
   joblib.dump(clf, full_model, compress=True)

   print 'Training done!'

else :
   
   full_model = '%s/%s_%s_%s_BDT.pkl' % (mods, dataset, args.jobtag, args.what)
   clf = joblib.load(full_model)
   print 'Loaded pre-existing model!'

#
# plot performance
#
from sklearn.metrics import roc_curve, roc_auc_score
args_dict = args.__dict__

rocs = {}
for df, name in [
   ##(train, 'train'),
   ##(test, 'test'),
   (validation, 'validation')
   ]:
   training_out = clf.predict_proba(df[features].as_matrix())[:, 1]
   rocs[name] = roc_curve(
      df.is_e.as_matrix().astype(int), 
      training_out)[:2]
   args_dict['%s_AUC' % name] = roc_auc_score(df.is_e, training_out)

with open('%s/%s_%s_%s_BDT.json' % (mods, dataset, args.jobtag, args.what), 'w') as info:
   json.dump(args_dict, info)

# make plots
plt.figure(figsize=[8, 8])
plt.title('%s training' % args.what.replace("_"," "))
plt.plot(
   np.arange(0,1,0.01),
   np.arange(0,1,0.01),
   'k--')
plt.plot(*rocs['validation'], label='Retraining (AUC: %.3f)'  % args_dict['validation_AUC'])
if args.what in ['seeding', 'fullseeding']:
   eff = float((validation.baseline & validation.is_e).sum())/validation.is_e.sum()
   mistag = float((validation.baseline & np.invert(validation.is_e)).sum())/np.invert(validation.is_e).sum()
   rocs['baseline'] = [[mistag], [eff]]
   plt.plot([mistag], [eff], 'o', label='baseline', markersize=5)   
elif 'id' in args.what:
   mva_v2 = roc_curve(validation.is_e, validation.ele_mvaIdV2)[:2]
   mva_v2_auc = roc_auc_score(validation.is_e, validation.ele_mvaIdV2)
   rocs['mva_v2'] = mva_v2
   plt.plot(*mva_v2, label='MVA ID V2 (AUC: %.2f)'  % mva_v2_auc)
else:
   pass #raise ValueError()

for key in rocs:
   fpr, tpr = rocs[key]
   rocs[key] = [list(fpr), list(tpr)]

with open('%s/%s_%s_%s_ROCS.json' % (plots, dataset, args.jobtag, args.what), 'w') as rr:
   rr.write(json.dumps(rocs))

plt.xlabel('Mistag Rate')
plt.ylabel('Efficiency')
plt.legend(loc='best')
plt.xlim(0., 1)
try : plt.savefig('%s/%s_%s_%s_BDT.png' % (plots, dataset, args.jobtag, args.what))
except : pass
try : plt.savefig('%s/%s_%s_%s_BDT.pdf' % (plots, dataset, args.jobtag, args.what))
except : pass
plt.gca().set_xscale('log')
plt.xlim(1e-4, 1)
try : plt.savefig('%s/%s_%s_%s_log_BDT.png' % (plots, dataset, args.jobtag, args.what))
except : pass
try : plt.savefig('%s/%s_%s_%s_log_BDT.pdf' % (plots, dataset, args.jobtag, args.what))
except : pass
plt.clf()
