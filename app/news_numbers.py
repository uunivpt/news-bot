"""Stable public identifiers. Internal database IDs remain untouched."""
import hashlib


def news_number(row):
    # Database IDs are never reassigned by this migration.
    key = 'id:' + str(row['id'])
    return str(100_000_000_000 + int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % 900_000_000_000)


def number_index(rows):
    index = {}
    for row in rows:
        number = news_number(row)
        previous = index.get(number)
        if previous and previous.get('url') != row.get('url'):
            raise ValueError('Public news number collision; publication must stop')
        index[number] = row
    return index
