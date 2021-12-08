import argparse
import logging
import os
import re
import sys
import urllib

from markdownify import markdownify
import requests
import yaml


logging.basicConfig(stream=sys.stdout, level=logging.ERROR)
log = logging.getLogger('wpmigrator')

class WordPressApi(object):
    def __init__(self):
        self.base_url = 'https://www.data.gov/wp-json/wp/v2'
        self.client = requests.Session()

    def fetch_all(self, collection, **params):
        response = self.get(collection, per_page=100, **params)
        response.raise_for_status()

        total_items = int(response.headers.get('x-wp-total'))
        total_pages = int(response.headers.get('x-wp-totalpages'))
        log.info(f'fetch_all collection={collection} total_items={total_items} total_pages={total_pages}')

        if total_items == 0:
            raise StopIteration

        for page in range(1, total_pages + 1):
            response = self.get(collection, page=page, per_page=100, order_by='id')
            response.raise_for_status()

            for item in response.json():
                log.debug(f'fetch_all {collection} id={item.get("id")} keys={item.keys()}')
                yield item

    def get(self, path, **params):
        return self.client.get(f'{self.base_url}/{path}', params=params)

class PageTemplater(object):
    def __init__(self, path, model_keys, tag_manager, category_manager, author_manager=None):
        self.path = path
        self.model_keys = model_keys
        self.tag_manager = tag_manager
        self.category_manager = category_manager
        self.author_manager = author_manager

    def template_frontmatter(self, model, additional=None):
        data = {}
        for key in self.model_keys:
            if key not in model:
                continue

            if key in ['content', 'title', 'excerpt', 'guid']:
                data[key] = model.get(key).get('rendered')
            elif key == 'tags':
                data[key] = [self.tag_manager.get_slug(tag_id) for tag_id in model.get(key)]
            elif key == 'categories':
                data[key] = [self.category_manager.get_slug(category_id) for category_id in model.get(key)]
            elif key == 'author':
                try:
                    data[key] = self.author_manager.get_slug(model.get(key))
                except KeyError as e:
                    log.error(f'author={model.get(key)} not found')
            else:
                data[key] = model.get(key)

        if additional:
            data.update(additional)

        return yaml.dump(data)

    def template_body(self, model):
        return model.get('content', {}).get('rendered')

    def redirects(self, model):
        # Only posts have multiple URLs for some reason
        if model.get('type') != 'post':
            return []

        permalink = self.permalink(model)
        title = permalink.split('/')[-2]

        # TODO Need to add category parents here too
        redirects = set()
        for category_id in model.get('categories'):
            redirect = f'/{self.category_manager.get_slug(category_id)}/{title}/'

            if permalink == redirect:
                continue

            # Add this redirect
            redirects.add(redirect)

            # Add parent categories, assume only one level of parent
            category = self.category_manager.get(category_id)
            parent_category_id = category.get('parent')
            if parent_category_id != 0:
                redirects.add(f'/{self.category_manager.get_slug(parent_category_id)}{redirect}')

        return list(redirects)


    def permalink(self, model):
        url = urllib.parse.urlparse(model.get('link'))
        path = url.path
        # Make sure to end with a /
        if not path.endswith('/'):
            path = path + '/'

        return path

    def get_filename(self, model):
        #title = re.sub(r'[^a-z0-9_]+', '-', model.get('title').get('rendered').lower())
        title = model.get('slug')
        return '%s.md' % title

    def template(self, model):
        additional = {}
        additional['permalink'] = self.permalink(model)
        additional['redirect_from'] = self.redirects(model)
        frontmatter = self.template_frontmatter(model, additional)
        body = self.template_body(model)
        filename = self.get_filename(model)

        try:
            with self.file_writer(filename) as f:
                f.write('---\n')
                f.write(frontmatter)
                f.write('---\n')
                f.write(markdownify(body))
        except Exception as e:
            log.exception(e)

    def file_writer(self, filename):
        path = os.path.join(self.path, filename)
        log.info(f'writing data for {path}')
        if os.path.exists(path):
            raise Exception(f'path={path} already exists')

        return open(path, 'wt')

class PostTemplater(PageTemplater):
    def get_filename(self, model):
        pattern = r'(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})'
        title = re.sub(r'[^a-z0-9_]+', '-', model.get('title').get('rendered').lower())
        date = re.match(pattern, model.get('date'))
        return '%s-%s-%s-%s.md' % (date.group('year'), date.group('month'), date.group('day'), title)


class DataTemplater(PageTemplater):
    def template(self, model):
        frontmatter = self.template_frontmatter(model)
        filename = '%s.yml' % model.get('slug')

        with self.file_writer(filename) as f:
            f.write(frontmatter)

    def template_frontmatter(self, model):
        data = {}
        for key in self.model_keys:
            if key in model:
                data[key] = model.get(key)

        return yaml.dump(data)



def template_authors(output, api, tag_manager, category_manager, author_manager):
    author_keys = [
        'id',
        'name',
        'url',
        'description',
        'slug',
        'meta',
        'acf',
    ]
    authors_path = os.path.join(output, '_data', 'authors')
    os.makedirs(authors_path, exist_ok=True)
    templater = DataTemplater(authors_path, author_keys, tag_manager, category_manager)
    for author in api.fetch_all('users'):
        templater.template(author)
        author_manager.add(author)

def index_categories(api, category_manager):
    for category in api.fetch_all('categories'):
        category_manager.add(category)

def index_tags(api, tag_manager):
    for tag in api.fetch_all('tags'):
        tag_manager.add(tag)


def template_posts(output, api, tag_manager, category_manager, author_manager):
    posts_keys = [
        'id',
        'date',
        'date_gmt',
        'guid',
        'modified',
        'modified_gmt',
        'slug',
        'status',
        'type',
        'link',
        'title',
        'excerpt',
        'author',
        'featured_media',
        'comment_status',
        'ping_status',
        'sticky',
        'template',
        'format',
        'meta',
        'categories',
        'tags',
        'acf',
    ]
    posts_path = os.path.join(output, '_posts')
    os.makedirs(posts_path, exist_ok=True)
    templater = PageTemplater(posts_path, posts_keys, tag_manager, category_manager, author_manager)
    for post in api.fetch_all('posts'):
        if tag_manager.is_filtered(post.get('tags')):
            # Skip any posts tagged with a filtered tag
            log.debug(f'skipping post={post.get("title")}')
            continue

        templater.template(post)
        # For each category...

def template_pages(output, api, tag_manager, category_manager, author_manager):
    pages_keys = [
        'id',
        'date',
        'date_gmt',
        'guid',
        'modified',
        'modified_gmt',
        'slug',
        'status',
        'type',
        'link',
        'title',
        'excerpt',
        'author',
        'featured_media',
        'comment_status',
        'ping_status',
        'sticky',
        'template',
        'format',
        'meta',
        'categories',
        'tags',
        'acf',
    ]
    templater = PageTemplater(output, pages_keys, tag_manager, category_manager, author_manager)
    for page in api.fetch_all('pages'):
        templater.template(page)

        # Create redirects for...
        # slug...
        # each category...

class EntityManager(object):
    def __init__(self, filter_list=None):
        self.tag_index = {}
        self.filtered_ids = []

        self.filter_list = []
        if filter_list:
            self.filter_list = filter_list

    def get_slug(self, tag_id):
        return self.tag_index[tag_id].get('slug')

    def get(self, tag_id):
        return self.tag_index[tag_id]

    def add(self, tag):
        id = tag.get('id')
        if id in self.tag_index:
            raise Exception(f'Entity id={id} already exists')

        if tag.get('name') in self.filter_list:
            self.filtered_ids.append(id)

        self.tag_index[id] = tag

    def is_filtered(self, tag_list):
        return any(tag_id in self.filtered_ids for tag_id in tag_list)


class Page(object):
    def process(self):
        # figure out the path to put the file
        # template the file to path
        # figure out what redirects to place
        pass



def main():
    log.setLevel(logging.INFO)
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--debug', action='store_true', help='use debug logging')
    parser.add_argument('--output', default='output', help='path to write the output files')
    args = parser.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    api = WordPressApi()
    # Get an index of categories
    log.info('Getting an index of categories...')
    category_manager = EntityManager()
    index_categories(api, category_manager)

    # Get an index of tags
    log.info('Getting an index of tags...')
    tag_manager = EntityManager(['usdatagov'])
    index_tags(api, tag_manager)

    # Get an index of authors/users
    log.info('Templating authors...')
    author_manager = EntityManager()
    template_authors(args.output, api, tag_manager, category_manager, author_manager)

    # Iterate over posts
    log.info('Templating posts...')
    template_posts(args.output, api, tag_manager, category_manager, author_manager)

    # Iterate over pages
    log.info('Templating pages...')
    template_pages(args.output, api, tag_manager, category_manager, author_manager)

if __name__ == '__main__':
    main()
