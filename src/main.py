import logging
import re
from collections import Counter
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import (BASE_DIR, EXPECTED_STATUS, MAIN_DOC_URL,
                       PDF_ZIP_FILE_PATTERN, PEP_DOC_URL,
                       PYTHON_DOC_VERSION_STATUS_PATTERN)
from exceptions import ParserFindTagException
from outputs import control_output
from utils import find_tag, get_response


def get_soup(session, url):
    response = get_response(session, url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    return soup


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    soup = get_soup(session, whats_new_url)
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li', attrs={'class': 'toctree-l1'})

    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        soup = get_soup(session, version_link)
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append((version_link, h1.text, dl_text,))
    return results


def latest_versions(session):
    soup = get_soup(session, MAIN_DOC_URL)
    sidebar = find_tag(soup, 'div', class_='sphinxsidebarwrapper')
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        error_msg = f'Ничего не нашлось в {ul}'
        logging.error(error_msg, stack_info=True)
        raise ParserFindTagException('error_msg')
    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    for a_tag in a_tags:
        ver_stat = re.search(PYTHON_DOC_VERSION_STATUS_PATTERN, a_tag.text)
        if ver_stat is None:
            version, status = a_tag.text, ''
        else:
            version, status = ver_stat.groups()
        results.append((a_tag['href'], version, status))
    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    soup = get_soup(session, downloads_url)
    main_tag = find_tag(soup, 'div', {'role': 'main'})
    table_tag = find_tag(main_tag, 'table', {'class': 'docutils'})
    pdf_a4_tag = find_tag(
        table_tag, 'a', {'href': re.compile(PDF_ZIP_FILE_PATTERN)})
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    soup = get_soup(session, PEP_DOC_URL)
    table_rows = soup.find_all('tr', attrs={'class': ['row-even', 'row-odd']})
    results = [('Статус', 'Итого')]
    all_results, urls = [], []
    for table_row in tqdm(table_rows):
        preview_status = table_row.find('abbr')
        if preview_status is None:
            continue
        pep_row = find_tag(
            table_row, 'a', attrs={'class': 'pep reference internal'})
        pep_url = urljoin(PEP_DOC_URL, pep_row['href'])
        if pep_url in urls:
            continue
        urls.append(pep_url)
        soup = get_soup(session, pep_url)
        doc_status = soup.find('abbr')
        if doc_status is None:
            continue
        all_results.append(doc_status.text)
        preview_status_expected = EXPECTED_STATUS[preview_status.text[1:]]
        if doc_status.text not in preview_status_expected:
            logging.info(f'''Несовпадающие статусы.
            {pep_url}
            Статус в карточке: {doc_status.text}
            Ожидаемые статусы: {preview_status_expected}''')
    sum_all_results = Counter(all_results)
    for status in set(all_results):
        results.append((status, sum_all_results[status]))
    results.append(('Total', len(all_results)))
    return results


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info('Парсер запущен!')
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)
    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
