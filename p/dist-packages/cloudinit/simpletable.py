try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO


class SimpleTable:
    """
    a minimal implementation of PrettyTable
    for distribution with cloud-init
    """

    def __init__(self, fields):
        self.fields = fields
        self.rows = []

        # initialize list of 0s the same length
        # as the number of fields
        self.column_widths = [0] * len(self.fields)
        self.update_column_widths(fields)

    def update_column_widths(self, values):
        for i, value in enumerate(values):
            self.column_widths[i] = max(
                len(value),
                self.column_widths[i])

    def add_row(self, values):
        if len(values) > len(self.fields):
            raise TypeError('too many values')
        values = [str(value) for value in values]
        self.rows.append(values)
        self.update_column_widths(values)

    def __repr__(self):
        out = StringIO()

        for i, column in enumerate(self.fields):
            out.write(column.center(self.column_widths[i] + 2))

        for row in self.rows:
            out.write('\n')
            for i, column in enumerate(row):
                out.write(column.center(self.column_widths[i] + 2))

        result = out.getvalue()
        out.close()
        return result

    def get_string(self):
        return repr(self)
