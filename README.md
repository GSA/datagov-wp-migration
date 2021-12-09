# datagov-wp-migration

Quick exploration of exporting content using the WordPress API.

Goals:
- maintain WordPress URLs


## Usage

Install python dependencies.

    $ pipenv install

Run the script.

    $ pipenv run python migrate.py

Test the site with Jekyll.

    $ bundle install
    $ bundle exec jekyll build

Copy the markdown files to GSA/datagov-website.

    $ cp -r output/ ../datagov-website/www.data.gov/
