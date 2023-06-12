from datetime import datetime
from io import BytesIO
import logging
import os
import pytz
import re
import sys
import urllib3

from bs4 import BeautifulSoup
from pydub import AudioSegment
import boto3
import nltk.data

# silence timing, in ms
PARAGRAPH_SILENCE = 557
SENTENCE_SILENCE = 316

# relative directory paths
PODCASTS_PATH = '../podcasts/'
POSTS_PATH = '../_posts/'

# link to ac10 archives
AC10_ARCHIVES = 'https://astralcodexten.substack.com/archive'


def get_audio(text):
    response = polly_client.synthesize_speech(
        VoiceId='Matthew', Engine='neural', OutputFormat='mp3', Text=text)
    seg = BytesIO()
    seg.write(response['AudioStream'].read())
    seg.seek(0)
    return seg

def parse_date(date):
    try:
        dt = datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%fZ')
    except ValueError:
        dt = datetime.now()
    return dt

if __name__ == '__main__':
    num = 0
    
    # check for -d flag for debug mode
    if len(sys.argv) > 1 and sys.argv[1] == '-d':
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # setup nltk tokenizer
    # uncomment following line on first run
    # nltk.download('punkt')
    tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')

    # setup polly client
    logging.debug('setting up polly client')
    polly_client = boto3.Session(
        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
        region_name='us-west-2').client('polly')

    # setup urllib pool manager
    logging.debug('setting up urllib pool manager')
    http = urllib3.PoolManager()

    # get and parse archives
    logging.debug('getting and parsing archives')
    res = http.request('GET', AC10_ARCHIVES)
    soup = BeautifulSoup(res.data, "html5lib")

    # get divs containing post links, iterate through list in reverse order
    divs = soup.find_all('div', attrs={'class': re.compile('PostPreviewListing-module__container')})
    logging.debug('found %d posts' % len(divs))
    for div in divs[::-1]:
        # get post url
        url = div.find('a', href=True)['href']
        date = div.find('time')['datetime']

        # get post name and build podcast filename
        name = url.split('/')[-1]
        filename = name + '.mp3'

        # check if filename already exists in podcasts folder, skip if so
        if filename in os.listdir(PODCASTS_PATH):
            continue

        # get post and parse
        res = http.request('GET', url)
        soup = BeautifulSoup(res.data, "html5lib")

        # get post content, get author, title, date, and time
        post = soup.find('article', attrs={'class': 'post'})
        author = 'Scott Alexander'
        title = post.find('h1', attrs={'class': 'post-title'}).text

        # create timezone aware datetime object from date and time
        dt = parse_date(date)
        dtz = pytz.timezone("US/Pacific").localize(dt)

        logging.info(dtz.strftime('%Y-%m-%d ') + name)

        # initialize pydub object, add introduction
        podcast = AudioSegment.silent(PARAGRAPH_SILENCE)
        intro = title + '\r\n\r\nPosted on ' + dtz.strftime("%B %d, %Y") + ' by ' + author
        podcast += AudioSegment.from_mp3(get_audio(intro))
        podcast += AudioSegment.silent(PARAGRAPH_SILENCE)

        # split post into paragraphs, iterate through list
        paragraphs = post.find_all('p')
        for paragraph in paragraphs:
            # split paragraph by new lines, iterate through list
            for line in paragraph.text.split('\n'):
                # split line into sentences, iterate through each
                sentences = tokenizer.tokenize(line)
                for sentence in sentences:
                    # add sentence audio and silence to podcast
                    podcast += AudioSegment.from_mp3(get_audio(sentence))
                    podcast += AudioSegment.silent(duration=SENTENCE_SILENCE)
                # add slightly longer pause between paragraphs
                podcast += AudioSegment.silent(PARAGRAPH_SILENCE -
                                               SENTENCE_SILENCE)

        # export podcast, get file duration and length
        podcast.export(
            PODCASTS_PATH +
            filename,
            format='mp3',
            tags={
                'artist': author,
                'title': title})
        duration = round(podcast.duration_seconds)
        length = os.stat(PODCASTS_PATH + filename).st_size

        # generate markdown text and write to post
        markdown = '''---\nlayout: podcast\ntitle: "%s"\nauthor: %s\ndescription: %s\ndate: %s\nlength: %d\nduration: %d\nguid: %s\n---''' % (
            title.replace('"', '\\"'), author, url, dtz.strftime('%Y-%m-%d'), length, duration, name)
        with open(POSTS_PATH + dtz.strftime('%Y-%m-%d-') + name + '.md', 'w') as f:
            f.write(markdown)

        # uncomment to process single post
        # break
        num += 1

    # return 0 if podcasts added, otherwise 1
    sys.exit(0 if num else 1)
