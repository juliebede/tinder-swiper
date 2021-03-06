'''
python -m pip install -U pip
python -m pip install -U flask python-dateutil pandas numpy
Download 64 bit OpenFace: https://github.com/TadasBaltrusaitis/OpenFace/wiki/Windows-Installation
Right click "download_models.ps1" and run with powershell
'''

from flask import Flask, request, render_template, jsonify
import os
from os import path, rename
from pathlib import Path
import base64

from openface_api.wrapper import process_pics
import glob
import pandas as pd
import numpy as np
import sys
import urllib.request
import shutil

sys.path.insert(0, 'tinder_api')
import tinder_api.session as session

# Init session
sess = session.Session()

# Set the like threshold
SIM_THRESHOLD = 200
P_AT_THRES = 0.66

STATIC_FOLDER = 'static/'
BASE_FOLDER = 'base/'
PROCESSED_FOLDER = 'processed/'
COMPARISON_FOLDER = 'comparison/'

app = Flask(__name__)
app._static_folder = STATIC_FOLDER

token_dict = {} # to keep track of currently active tokens


@app.route('/')
def root():
    #return app.send_static_file('markup/matches.html')
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
        process_pics(filepath, csv_only=False)

        # Move the csv and into base
        processed_file = token + '.csv'
        rename(PROCESSED_FOLDER + processed_file, BASE_FOLDER + processed_file)

        base64_image = base64_encode(PROCESSED_FOLDER + filename)

        # Delete files in processed
        files_to_del = glob.glob(PROCESSED_FOLDER + str(token) + '*')
        for fp in files_to_del:
            try:
                remove(fp)
            except:
                print('Error while deleting file: ' + fp)

        
        return render_template('matches.html', token=token, image=base64_image)
    else:
        return 'Image not recieved', 400


@app.route('/api/match', methods=['GET'])
def match() -> None:
    token = request.args['token']
    if token:
        if token in token_dict and token_dict[token]:
            return 'Previous request in progress', 400
        token_dict[token] = True
        
        download_dir = COMPARISON_FOLDER + str(token) + '/'
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        
        # Get info for one user
        print('Token:', token)
        print('Yielding user info...')
        user = next(sess.yield_users())
        
        # Store their info
        name = user.name
        age = user.age
        gender = user.gender
        bio = user.bio if type(user.bio) == str else ""
        pic = ""
        liked = False
        matched = False
        dist_val = -10
        
        # Download pictures to /comparison/token/token{0-X}
        print('Downloading {0} pics...'.format(len(user.photos)))
        download_image(user.photos, token, download_dir)
        
        # Run open face in whole dir
        print('Processing pics...')
        process_pics(in_dir=download_dir, csv_only=False)
        
        # Determine the similarity score
        sim_results = batch_compare(BASE_FOLDER + str(token) + '.csv', PROCESSED_FOLDER)
        
        # Swipe right or left and select best pic to send
        # this indicates that there were no faces detected in any of the user's photos
        if sim_results == -1: 
            pic = base64_encode(PROCESSED_FOLDER + str(token) + '_0.jpg')
            print('No face', sim_results)
            dist_val = sim_results
            user.dislike()
            
        elif sim_results[1] >= SIM_THRESHOLD:
            pic = base64_encode(PROCESSED_FOLDER + sim_results[0] + '.jpg')
            print('Dislike', sim_results)
            dist_val = sim_results[1]
            user.dislike()
            
        elif sim_results[1] < SIM_THRESHOLD:
            pic = base64_encode(PROCESSED_FOLDER + sim_results[0] + '.jpg')
            print('Like', sim_results)
            dist_val = sim_results[1]
            matched = user.like()
            liked = True
            
        # Generate a likelihood percentage based off dist_val
        match_percent = match_likelihood(dist_val)
                     
        # Build return_json
        user_info = ['name', 'age', 'gender', 'bio', 'pic', 'liked', 'dist_val', 'matched', 'match_percent']
        return_json = {k:eval(k) for k in user_info}
        
        # Delete CSVs from processed
        files_to_del = glob.glob(PROCESSED_FOLDER + str(token) + '*')
        
        for fp in files_to_del:
            try:
                remove(fp)
            except:
                print('Error while deleting file:', fp)
        
        # Delete downloaded pics
        try:
            remove(download_dir)
        except:
            print('Error while deleting directory:', download_dir)
        
        print()
        token_dict[token] = False
        return jsonify(return_json)

def compare(base_fp: str, comparison_fp: str) -> float:
    """ Returns the distance between base and comparison. Returns 
        lowest distance if there are multiple faces.
        Base and comparison are filepaths to CSVs.
    """
    base_arr = pd.read_csv(base_fp).loc[0, ' x_0':' y_67'].values
    comparison_arr = pd.read_csv(comparison_fp).loc[:, ' x_0':' y_67'].values
    
    if comparison_arr.shape[0] == 1:
        return np.sqrt(np.sum((base_arr - comparison_arr) ** 2) / len(base_arr))
    
    elif comparison_arr.shape[0] > 1:
        dist = float('inf')
        
        for row in comparison_arr:
            d = np.sqrt(np.sum((base_arr - row) ** 2) / len(base_arr))
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

def download_image(img_lst, name, ddir, pic_limit=3) -> None:
    """ This function takes in a list of images, along with a name for the 
        output and downloads them into a directory.
    """
    for i, img_link in enumerate(img_lst):
        if i == pic_limit - 1:
            break
        urllib.request.urlretrieve(img_link, ddir + str(name) + '_' + str(i) + '.jpg')

def base64_encode(in_file: str) -> str:
    with open(in_file, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()) 
    return "data:image/jpeg;base64," + str(encoded_string)[2:-1]

def remove(path) -> None:
    """ param <path> could either be relative or absolute. """
    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)  # remove the file
    elif os.path.isdir(path):
        shutil.rmtree(path)  # remove dir and all contains
    else:
        raise ValueError("file {} is not a file or dir.".format(path))

def match_likelihood(dist_val) -> float:
    """ y=b/(x+b) 
    where x = P_AT_THRES;
          y = SIM_THRESHOLD
    """
    
    b = -(P_AT_THRES * SIM_THRESHOLD) / (P_AT_THRES - 1)
    
    if dist_val < 0:
        return 0
    else:
        return  b / (dist_val + b)

if __name__ == "__main__":
    app.run()
