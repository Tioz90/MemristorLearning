import argparse
import time

import nengo_dl
from nengo.dists import Gaussian
from nengo.learning_rules import PES
from nengo.processes import WhiteNoise, WhiteSignal

from memristor_nengo.extras import *
from memristor_nengo.learning_rules import mPES

start_time = time.time()

setup()

parser = argparse.ArgumentParser()
parser.add_argument( "-E", "--experiment", choices=[ 1, 2, 3, 4, 5 ], type=int,
                     help="1: Product 2: Combined product" )
parser.add_argument( "-T", "--sim_time", default=None, type=float )
parser.add_argument( "-I", "--iterations", default=10, type=int )
parser.add_argument( "-g", "--gain", default=1e3, type=float )
parser.add_argument( "-d", "--device", default="/cpu:0" )
parser.add_argument( '--decoded', dest='decoded', action='store_true' )
parser.add_argument( '--no-decoded', dest='decoded', action='store_false' )
parser.set_defaults( decoded=True )
args = parser.parse_args()

experiment = args.experiment
if experiment == 1:
    exp_string = "PRODUCT experiment"
    exp_name = "Multiplying two numbers"
    function_to_learn = lambda x: x[ 0 ] * x[ 1 ]
    # [ pre, post, ground_truth, error ]
    neurons = [ 200, 200, 100, 100 ]
    dimensions = [ 2, 1, 1, 1 ]
    sim_time = 50
if experiment == 2:
    exp_string = "COMBINED PRODUCTS experiment"
    exp_name = "Combining two products"
    function_to_learn = lambda x: x[ 0 ] * x[ 1 ] + x[ 2 ] * x[ 3 ]
    # [ pre, post, ground_truth, error ]
    neurons = [ 400, 400, 100, 100 ]
    dimensions = [ 4, 1, 1, 1 ]
    sim_time = 100
if experiment == 3:
    exp_string = "SEPARATE PRODUCTS experiment"
    exp_name = "Three separate products"
    function_to_learn = lambda x: [ x[ 0 ] * x[ 1 ], x[ 0 ] * x[ 2 ], x[ 1 ] * x[ 2 ] ]
    # [ pre, post, ground_truth, error ]
    neurons = [ 300, 300, 300, 300 ]
    dimensions = [ 3, 3, 3, 3 ]
    sim_time = 100
if experiment == 4:
    exp_string = "2D CIRCULAR CONVOLUTIONS experiment"
    exp_name = "Two-dimensional circular convolution"
    # [ pre, post, ground_truth, error,conv ]
    neurons = [ 400, 400, 200, 200, 200 ]
    dimensions = [ 4, 2, 2, 2, 2 ]
    function_to_learn = lambda x: np.fft.ifft(
            np.fft.fft( x[ :int( dimensions[ 0 ] / 2 ) ] ) * np.fft.fft( x[ int( dimensions[ 0 ] / 2 ): ] )
            )
    sim_time = 200
if experiment == 5:
    exp_string = "3D CIRCULAR CONVOLUTIONS experiment"
    exp_name = "Three-dimensional circular convolution"
    # [ pre, post, ground_truth, error,conv ]
    neurons = [ 600, 300, 300, 300, 300 ]
    dimensions = [ 6, 3, 3, 3, 3 ]
    function_to_learn = lambda x: np.fft.ifft(
            np.fft.fft( x[ :int( dimensions[ 0 ] / 2 ) ] ) * np.fft.fft( x[ int( dimensions[ 0 ] / 2 ): ] )
            )
    sim_time = 400

assert 'exp_name' in locals()

if args.sim_time is not None:
    sim_time = args.sim_time
iterations = args.iterations
gain = args.gain
learn_block_time = 2.5
# to have an extra testing block at t=[0,2.5]
sim_time += learn_block_time
device = args.device
directory = "../data/"
seed = 0
convolve = False if experiment <= 3 else True
decoded = args.decoded

print( exp_string )
dir_name, dir_images, dir_data = make_timestamped_dir(
        root=directory + "trevor/" + exp_name + "/" )
print( "Reserved folder", dir_name )


def LearningModel( neurons, dimensions, learning_rule, function_to_learn, convolve, seed ):
    global decoded
    
    with nengo.Network() as model:
        
        nengo_dl.configure_settings( stateful=False )
        
        model.inp = nengo.Node(
                # WhiteNoise( dist=Gaussian( 0, 0.05 ), seed=seed ),
                WhiteSignal( sim_time, high=5, seed=seed ),
                size_out=dimensions[ 0 ]
                )
        model.pre = nengo.Ensemble( neurons[ 0 ], dimensions=dimensions[ 0 ], seed=seed )
        model.post = nengo.Ensemble( neurons[ 1 ], dimensions=dimensions[ 1 ], seed=seed )
        model.ground_truth = nengo.Ensemble( neurons[ 2 ], dimensions=dimensions[ 2 ], seed=seed )
        
        nengo.Connection( model.inp, model.pre )
        
        if convolve:
            model.conv = nengo.networks.CircularConvolution( neurons[ 4 ], dimensions[ 4 ], seed=seed )
            nengo.Connection( model.inp[ :int( dimensions[ 0 ] / 2 ) ],
                              model.conv.input_a,
                              synapse=None )
            nengo.Connection( model.inp[ int( dimensions[ 0 ] / 2 ): ],
                              model.conv.input_b,
                              synapse=None )
            nengo.Connection( model.conv.output, model.ground_truth,
                              synapse=None )
        else:
            nengo.Connection( model.inp, model.ground_truth,
                              function=function_to_learn,
                              synapse=None )
        
        if learning_rule:
            model.error = nengo.Ensemble( neurons[ 3 ], dimensions=dimensions[ 3 ], seed=seed )
            
            if isinstance( learning_rule, mPES ) or (isinstance( learning_rule, PES ) and not decoded):
                model.conn = nengo.Connection(
                        model.pre.neurons,
                        model.post.neurons,
                        transform=np.random.random(
                                (model.post.n_neurons, model.pre.n_neurons)
                                ),
                        learning_rule_type=learning_rule
                        )
            else:
                model.conn = nengo.Connection(
                        model.pre,
                        model.post,
                        function=lambda x: np.random.random( dimensions[ 1 ] ),
                        learning_rule_type=learning_rule
                        )
            nengo.Connection( model.error, model.conn.learning_rule )
            nengo.Connection( model.post, model.error )
            nengo.Connection( model.ground_truth, model.error, transform=-1 )
            
            class cyclic_inhibit:
                def __init__( self, cycle_time ):
                    self.out_inhibit = 0.0
                    self.cycle_time = cycle_time
                
                def step( self, t ):
                    if t % self.cycle_time == 0:
                        if self.out_inhibit == 0.0:
                            self.out_inhibit = 2.0
                        else:
                            self.out_inhibit = 0.0
                    
                    return self.out_inhibit
            
            model.inhib = nengo.Node( cyclic_inhibit( learn_block_time ).step )
            nengo.Connection( model.inhib, model.error.neurons,
                              transform=[ [ -1 ] ] * model.error.n_neurons )
        else:
            model.conn = nengo.Connection(
                    model.pre,
                    model.post,
                    function=function_to_learn
                    )
        
        # -- probes
        model.pre_probe = nengo.Probe( model.pre, synapse=0.01 )
        model.post_probe = nengo.Probe( model.post, synapse=0.01 )
        model.ground_truth_probe = nengo.Probe( model.ground_truth, synapse=0.01 )
        # function_learning_model.error_probe = nengo.Probe( function_learning_model.error, synapse=0.03 )
    
    return model


# trail runs for each model
errors_iterations_mpes = [ ]
errors_iterations_pes = [ ]
errors_iterations_nef = [ ]
for i in range( iterations ):
    
    learned_model_mpes = LearningModel( neurons, dimensions, mPES( gain=gain ), function_to_learn,
                                        convolve=convolve, seed=seed + i )
    control_model_pes = LearningModel( neurons, dimensions, PES(), function_to_learn,
                                       convolve=convolve, seed=seed + i )
    control_model_nef = LearningModel( neurons, dimensions, None, function_to_learn,
                                       convolve=convolve, seed=seed + i )
    
    print( "Iteration", i )
    with nengo_dl.Simulator( learned_model_mpes, device=device ) as sim_mpes:
        print( "Learning network (mPES)" )
        sim_mpes.run( sim_time )
    with nengo_dl.Simulator( control_model_pes, device=device ) as sim_pes:
        print( "Control network (PES)" )
        sim_pes.run( sim_time )
    with nengo_dl.Simulator( control_model_nef, device=device ) as sim_nef:
        print( "Control network (NEF)" )
        sim_nef.run( sim_time )
    
    # essential statistics
    num_blocks = int( sim_time / learn_block_time )
    num_testing_blocks = int( num_blocks / 2 )
    for sim, mod, lst in zip( [ sim_mpes, sim_pes, sim_nef ],
                              [ learned_model_mpes, control_model_pes, control_model_nef ],
                              [ errors_iterations_mpes, errors_iterations_pes, errors_iterations_nef ] ):
        # split probe data into the trial run blocks
        ground_truth_data = np.array_split( sim.data[ mod.ground_truth_probe ], sim_time / learn_block_time )
        post_data = np.array_split( sim.data[ mod.post_probe ], sim_time / learn_block_time )
        # extract learning blocks
        train_ground_truth_data = np.array( [ x for i, x in enumerate( ground_truth_data ) if i % 2 != 0 ] )
        test_ground_truth_data = np.array( [ x for i, x in enumerate( ground_truth_data ) if i % 2 == 0 ] )
        # extract testing blocks
        train_post_data = np.array( [ x for i, x in enumerate( post_data ) if i % 2 != 0 ] )
        test_post_data = np.array( [ x for i, x in enumerate( post_data ) if i % 2 == 0 ] )
        
        # compute testing error for learn network
        total_error = np.sum( np.sum( np.abs( test_post_data - test_ground_truth_data ), axis=1 ), axis=1 )
        lst.append( total_error )


# 95% confidence interval
def ci( data, confidence=0.95 ):
    from scipy.stats import norm
    
    z = norm.ppf( (1 + confidence) / 2 )
    
    return np.mean( data, axis=0 ), \
           np.mean( data, axis=0 ) + z * np.std( data, axis=0 ) / np.sqrt( len( data ) ), \
           np.mean( data, axis=0 ) - z * np.std( data, axis=0 ) / np.sqrt( len( data ) )


# compute mean testing error and confidence intervals
ci_mpes = ci( errors_iterations_mpes )
ci_pes = ci( errors_iterations_pes )
ci_nef = ci( errors_iterations_nef )

# plot testing error
fig, ax = plt.subplots()
fig.set_size_inches( (14, 8) )
plt.title( exp_name )
x = (np.arange( num_testing_blocks + 1 ) * 2 * learn_block_time).astype( np.int )
ax.set_ylabel( "Total error" )
ax.set_xlabel( "Seconds" )

ax.plot( x, ci_mpes[ 0 ], label="Learned (mPES)", c="g" )
ax.plot( x, ci_mpes[ 1 ], linestyle="--", alpha=0.5, c="g" )
ax.plot( x, ci_mpes[ 2 ], linestyle="--", alpha=0.5, c="g" )
ax.plot( x, ci_pes[ 0 ], label="Control (PES)", c="b" )
ax.plot( x, ci_pes[ 1 ], linestyle="--", alpha=0.5, c="b" )
ax.plot( x, ci_pes[ 2 ], linestyle="--", alpha=0.5, c="b" )
ax.plot( x, ci_nef[ 0 ], label="Control (NEF)", c="r" )
ax.plot( x, ci_nef[ 1 ], linestyle="--", alpha=0.5, c="r" )
ax.plot( x, ci_nef[ 2 ], linestyle="--", alpha=0.5, c="r" )
ax.plot( x, ci_mpes[ 0 ], "-gX", markevery=[ 0 ] )
ax.plot( x, ci_pes[ 0 ], "-bX", markevery=[ 0 ] )
ax.plot( x, ci_nef[ 0 ], "-rX", markevery=[ 0 ] )
ax.legend( loc="best" )
fig.show()

# noinspection PyTypeChecker
np.savetxt( dir_data + "results.csv",
            np.squeeze(
                    np.stack(
                            (ci_mpes[ 0 ], ci_mpes[ 1 ], ci_mpes[ 2 ],
                             ci_pes[ 0 ], ci_pes[ 1 ], ci_pes[ 2 ],
                             ci_nef[ 0 ], ci_nef[ 1 ], ci_nef[ 2 ],
                             ),
                            axis=1
                            )
                    ),
            delimiter=",",
            header="Mean mPES error,CI mPES +,CI mPES -,"
                   "Mean PES error,CI PES +,CI PES -,"
                   "Mean NEF error,CI NEF +,CI NEF -,",
            comments="" )
print( exp_string )
print( f"Saved results in {dir_data}" )
fig.savefig( dir_images + "product" + ".pdf" )
print( f"Saved plots in {dir_images}" )

end_time = time.time()
print( f"Elapsed time: {datetime.timedelta( seconds=np.ceil( end_time - start_time ) )} (h:mm:ss)" )
