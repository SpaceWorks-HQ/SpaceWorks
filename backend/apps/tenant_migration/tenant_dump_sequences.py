"""Exact Lane D sequence normalization and restored-state inspection."""

from django.db import connections


def normalize_sequences(using):
    connection = connections[using]
    normalized = {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, column_name,
                   pg_get_serial_sequence(format('%I.%I', table_schema, table_name), column_name)
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND pg_get_serial_sequence(
                    format('%I.%I', table_schema, table_name), column_name
               ) IS NOT NULL
             ORDER BY table_name, column_name
            """
        )
        sequences = cursor.fetchall()
        quote = connection.ops.quote_name
        for table, column, sequence in sequences:
            cursor.execute(f"SELECT MAX({quote(column)}) FROM {quote(table)}")
            maximum = cursor.fetchone()[0]
            if maximum is None:
                cursor.execute(
                    "SELECT seqstart FROM pg_sequence WHERE seqrelid = %s::regclass",
                    [sequence],
                )
                value, called = cursor.fetchone()[0], False
            else:
                value, called = maximum, True
            cursor.execute(
                "SELECT setval(%s::regclass, %s, %s)",
                [sequence, value, called],
            )
            normalized[sequence] = (value, called)
    return normalized


def read_sequence_state(using):
    connection = connections[using]
    state = {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT n.nspname || '.' || c.relname
              FROM pg_sequence sequence_row
              JOIN pg_class c ON c.oid = sequence_row.seqrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
             ORDER BY c.relname
            """
        )
        for (sequence,) in cursor.fetchall():
            quoted = ".".join(
                connection.ops.quote_name(part)
                for part in sequence.split(".", 1)
            )
            cursor.execute(f"SELECT last_value, is_called FROM {quoted}")
            state[sequence] = tuple(cursor.fetchone())
    return state
