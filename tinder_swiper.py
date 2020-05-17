'''
python -m pip install -U pip
python -m pip install -U flask python-dateutil wget pandas numpy glob
'''

from flask import Flask, request, render_template
import os
from os import path, rename
from pathlib import Path

import glob
import pandas as pd
import numpy as np

from openface_api.wrapper import process_pics
import glob
import pandas as pd
import numpy as np
import sys

sys.path.insert(0, 'tinder_api')
import tinder_api.session

# Any distance value below this will be liked
SIM_THRESHOLD = 300

STATIC_FOLDER = 'static/'
BASE_FOLDER = 'base/'
PROCESSED_FOLDER = 'processed/'
COMPARISON_FOLDER = 'comparison/'

app = Flask(__name__)
app._static_folder = STATIC_FOLDER

sess = tinder_api.session.Session()

@app.route('/')
def root():
    return app.send_static_file('markup/tinder_swiper.html')

# Respond with token that the user can use to acess a preview of the profiles in real time
#   Token is a hash of the image sent (sha1? murmur2?)
@app.route('/matches', methods=['POST'])
def matches() -> None:
    file = request.files['file']
    if file and '.' in file.filename:
        # Create a hash and save it
        token = str(hash(file))
        filename = token + '.' + file.filename.rsplit('.', 1)[1]
        Path(BASE_FOLDER).mkdir(parents=True, exist_ok=True)
        filepath = BASE_FOLDER + filename
        file.save(filepath)

        # Create a base image
        process_pics(filepath)

        # Move the csv into base
        processed_file = token + '.csv'
        rename(PROCESSED_FOLDER + processed_file, BASE_FOLDER + processed_file)
                
        return render_template('templates/matches.html', token=token, image=filepath)
    else:
        return 'Image not recieved', 400

@app.route('/api/match', methods=['GET'])
def match() -> None:
    token = request.args['token']
    if token:
        # Init session
        sess = session.Session()
        
        Path(COMPARISON_FOLDER).mkdir(parents=True, exist_ok=True)
        download_dir = COMPARISON_FOLDER + str(token) + '/'
        
        # Get info for one user
        user = next(sess.yield_users())        
        user_name = user.name
        user_bio = user.bio 
        liked = False
        
        # Download pictures to /comparison/token/token{0-X}
        download_image(user.photos, token, download_dir)
        
        # Run open face in whole dir
        process_pics(in_dir=download_dir)
        
        # Determine the similarity score
        sim_results = batch_compare(BASE_FOLDER + str(token) + '.csv', PROCESSED_FOLDER)
        
        # Swipe right or left
        if sim_results == -1:
            user.dislike()
        elif sim_results[1] >= SIM_THRESHOLD:
            user.dislike()
        elif sim_results[1] < SIM_THRESHOLD:
            user.like()
            liked = True
        
        # Send best picture in comparison dir
        # For picture in comparison dir, delete picture and corresponding pic in processed


def compare(base_fp: str, comparison_fp: str) -> float:
    """ Returns the distance between base and comparison. Returns 
        lowest distance if there are multiple faces.
        Base and comparison are filepaths to CSVs.
    """
    base_arr = pd.read_csv(base_fp).loc[:, ' x_0':' y_67'].values
    comparison_arr = pd.read_csv(comparison_fp).loc[:, ' x_0':' y_67'].values
    
    if comparison_arr.shape[0] == 1:
        return np.sqrt(np.sum((base_arr - comparison_arr) ** 2) / base_arr.shape[1])
    
    elif comparison_arr.shape[0] > 1:
        dist = float('inf')
        
        for row in comparison_arr:
            d = np.sqrt(np.sum((base_arr - row) ** 2) / base_arr.shape[1])
            if d < dist: dist = d

        return dist
    
def batch_compare(base_fp: str, comparison_dir: str) -> tuple:
    """ Compare the base CSV to a directory containing comparison CSVs.
        Returns a tuple containing the (name of file and distance value).
        The tuple contains the comparison csv that is the most similar to base.
    """
    results = {}
    comparison_csv_lst = glob.glob(comparison_dir + '/*.csv')
    
    if not comparison_csv_lst:
        return -1
    else:
        for comparison_csv in comparison_csv_lst:
            filename = os.path.split(comparison_csv)[1].split('.')[0]
            results[filename] = compare(base_fp, comparison_csv)
        
    return (min(results, key=results.get), results[min(results, key=results.get)])

if __name__ == "__main__":
    app.run()
