from __future__ import print_function
import pickle
import os.path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from oauth2client.service_account import ServiceAccountCredentials
import click
import io
import os
import glob
import re
import mimetypes

# If modifying these scopes, delete the file token.pickle.
SCOPES = [
    'https://www.googleapis.com/auth/drive.metadata.readonly',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive.appdata',
    'https://www.googleapis.com/auth/drive.scripts',
    'https://www.googleapis.com/auth/drive.metadata'
]

FOLDER_TYPE = 'application/vnd.google-apps.folder'

def setup(service_account_url = "service-account.json"):
    """Shows basic usage of the Drive v3 API.
    Prints the names and ids of the first 10 files the user has access to.
    """
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("Authenticating... ", end='')
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                service_account_url,
                scopes=SCOPES
            )
            print("Done")
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('drive', 'v3', credentials=creds)

    return service

def echo(message):
    click.echo(message)

@click.group()
@click.option('-a', '--auth', default="service-account.json", help="Use service account for authentication")
@click.option('-s', '--silent', is_flag=True, help="Output should be silent")
@click.pass_context
def gdrive(ctx, auth, silent):
    """Google Drive Service"""

    ctx.ensure_object(dict)
    ctx.obj['service'] = setup(auth)

@gdrive.command()
@click.argument('unit_id')
@click.argument('save_to')
@click.pass_context
def download(ctx, unit_id, save_to):
    parent_state = ctx.obj
    service = parent_state['service']
    download_unit(service, unit_id, save_to)

def clean_path(path):
    return re.sub("\/$", "", path)

def download_unit(service, unit_id, save_to):
    unit = service.files().get(fileId=unit_id, fields='id, name, mimeType, version').execute()

    unit_is_directory = unit['mimeType'] == FOLDER_TYPE

    if unit_is_directory:
        download_folder(service, unit_id, save_to)
    else:
        download_file(service, unit, save_to + "/" + unit['name'])

def download_folder(service, folder_id, save_path="."):
    save_path = clean_path(save_path)
    if not os.path.isdir(save_path):
        os.mkdir(save_path)

    query = "'{}' in parents".format(folder_id)
    results = service.files().list(fields="nextPageToken, files(id, name, mimeType, version)", q=query).execute()

    items = results.get('files', [])

    for item in items:
        save_file_path = "{}/{}".format(save_path, item['name'])
        if item['mimeType'] == FOLDER_TYPE:
            download_folder(service, item['id'], save_file_path)
        else:
            download_file(service, item, save_file_path)

def download_file(service, item, save_path = "."):
    save_path = clean_path(save_path)
    request = service.files().get_media(fileId=item['id'])
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False

    try:
        while done is False:
            status, done = downloader.next_chunk()
            echo("Download and create file {} [{}%].".format(save_path, int(status.progress() * 100)))

        with io.open(save_path, 'wb') as f:
            fh.seek(0)
            f.write(fh.read())
    except HttpError as error:
        if error.resp.status == 416:
            # Create empty file
            open(save_path, 'a').close()
            echo("Create empty file {}".format(save_path))

@gdrive.command()
@click.argument('source_path')
@click.argument('folder_id')
@click.pass_context
def upload(ctx, source_path, folder_id):
    parent_state = ctx.obj
    service = parent_state['service']
    upload_unit(service, source_path, folder_id)

def upload_unit(service, src, folder_id):
    src = clean_path(src)

    if os.path.isdir(src):
        unit_is_directory = True
    elif os.path.isfile(src):
        unit_is_directory = False
    else:
        raise ValueError("Can't find {}".format(src))

    if unit_is_directory:
        upload_folder(service, src, folder_id)
    else:
        upload_file(service, src, folder_id)

def get_unit(service, unit_name, folder_id, is_directory=False):
    query = "'{}' in parents".format(folder_id)
    results = service.files().list(fields="nextPageToken, files(id, name, mimeType, version)", q=query).execute()
    
    for remote_file in results.get('files', []):
        if remote_file['name'] == unit_name and (not is_directory or remote_file['mimeType'] == FOLDER_TYPE):
            return remote_file
    return None

def upload_folder(service, src, folder_id):
    for file_name in os.listdir(src):
        path = "{}/{}".format(src, file_name)
        if os.path.isdir(path):
            remote_folder = get_unit(service, file_name, folder_id, is_directory=True)

            # Create new folder
            if remote_folder == None:
                file_metadata = {
                    'name': file_name,
                    'mimeType': FOLDER_TYPE,
                    'parents': [folder_id]
                }
                folder = service.files().create(body=file_metadata, fields='id').execute()
                new_folder_id = folder['id']
            else:
                new_folder_id = remote_folder['id']

            upload_folder(service, path, new_folder_id)
        else:
            upload_file(service, path, folder_id)

def upload_file(service, src, folder_id):
    src = clean_path(src)
    name = os.path.basename(src)
    remote_file = get_unit(service, name, folder_id)

    if remote_file == None:
        file_metadata = {
            'name': name,
            'parents': [folder_id],
        }

        media = MediaFileUpload(
            src,
            mimetype=mimetypes.guess_type(src)[0],
        )

        f = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        echo('Uploaded {}'.format(src))
    else:
        media = MediaFileUpload(
            src,
            mimetype=mimetypes.guess_type(src)[0],
        )

        folder = service.files().update(fileId=remote_file['id'], media_body=media).execute()
        echo('Updated {}'.format(src))
