"""WebDAV client for fetching Zotero attachments from WebDAV server."""

import io
import logging
from pathlib import Path
from urllib.parse import urljoin

import requests
from zipfile import ZipFile

logger = logging.getLogger(__name__)


class WebDAVClient:
    """Client for fetching Zotero attachments from WebDAV server."""

    def __init__(self, webdav_url, username=None, password=None, auth_type='basic'):
        self.webdav_url = webdav_url.rstrip('/') + '/'
        self.username = username
        self.password = password
        self.auth_type = auth_type.lower()
        self.session = requests.Session()
        
        if self.username and self.password:
            if self.auth_type == 'bearer':
                self.session.headers['Authorization'] = f'Bearer {self.password}'
            else:
                self.session.auth = (self.username, self.password)

    def _get_file_url(self, item_key):
        return f"{self.webdav_url.rstrip('/')}/{item_key}.zip"

    def get_attachment_from_zip(self, item_key):
        zip_url = self._get_file_url(item_key)
        
        try:
            logger.info(f"Fetching attachment from WebDAV: {zip_url}") # changed from debug to info so we can see it
            response = self.session.get(zip_url, timeout=60)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.debug(f"WebDAV file not found or error: {item_key}.zip - {e}")
            return None
        
        zip_bytes = response.content
        return self._extract_attachment_from_zip(zip_bytes, item_key)

    def _extract_attachment_from_zip(self, zip_bytes, item_key):
        try:
            with ZipFile(io.BytesIO(zip_bytes)) as zf:
                namelist = zf.namelist()
                logger.debug(f"Zip contents for {item_key}: {namelist}")
                
                if not namelist:
                    logger.warning(f"Empty zip file for item: {item_key}")
                    return None
                
                attachment_file = None
                for filename in namelist:
                    if filename.startswith('__MACOSX') or filename == '.DS_Store':
                        continue
                    if filename.endswith('.xml'):
                        continue
                    if not filename.endswith('/'):
                        attachment_file = filename
                        break
                
                if not attachment_file:
                    logger.warning(f"Could not find attachment file in zip for: {item_key}")
                    return None
                
                with zf.open(attachment_file) as f:
                    file_bytes = f.read()
                
                ext = Path(attachment_file).suffix.lower()
                if ext == '.pdf':
                    content_type = 'application/pdf'
                elif ext == '.epub':
                    content_type = 'application/epub+zip'
                elif ext in ('.html', '.htm'):
                    content_type = 'text/html'
                else:
                    content_type = 'application/octet-stream'
                
                logger.debug(f"Extracted attachment: {attachment_file} ({content_type})")
                return (file_bytes, attachment_file, content_type)
                
        except Exception as e:
            logger.warning(f"Failed to extract attachment from zip for {item_key}: {e}")
            return None

    def file_exists(self, item_key):
        zip_url = self._get_file_url(item_key)
        try:
            response = self.session.head(zip_url, timeout=30)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False


def get_webdav_client():
    from src.config import WEBDAV_URL, WEBDAV_USERNAME, WEBDAV_PASSWORD, WEBDAV_AUTH_TYPE
    
    if not WEBDAV_URL:
        return None
    return WebDAVClient(WEBDAV_URL, WEBDAV_USERNAME, WEBDAV_PASSWORD, WEBDAV_AUTH_TYPE)
