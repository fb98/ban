import uuid

import peewee

from ban import db

from .validators import ResourceValidator


class ResourceQueryResultWrapper(peewee.ModelQueryResultWrapper):

    def process_row(self, row):
        instance = super().process_row(row)
        return instance.as_resource


class ResourceListQueryResultWrapper(peewee.ModelQueryResultWrapper):

    def process_row(self, row):
        instance = super().process_row(row)
        return instance.as_relation


class SelectQuery(db.SelectQuery):

    @peewee.returns_clone
    def as_resource(self):
        self._result_wrapper = ResourceQueryResultWrapper

    @peewee.returns_clone
    def as_resource_list(self):
        self._result_wrapper = ResourceListQueryResultWrapper


class BaseResource(peewee.BaseModel):

    def include_field_for_compact(cls, name):
        if name in ['version', 'created_at', 'created_by', 'modified_at',
                    'modified_by']:
            return False
        attr = getattr(cls, name, None)
        exclude = (db.ManyToManyField, peewee.ReverseRelationDescriptor,
                   peewee.SelectQuery)
        if not attr or isinstance(attr, exclude):
            return False
        return True

    def __new__(mcs, name, bases, attrs, **kwargs):
        # Inherit and extend instead of replacing.
        resource_fields = attrs.pop('resource_fields', None)
        resource_schema = attrs.pop('resource_schema', None)
        cls = super().__new__(mcs, name, bases, attrs, **kwargs)
        if resource_fields is not None:
            inherited = getattr(cls, 'resource_fields', {})
            resource_fields.extend(inherited)
            cls.resource_fields = resource_fields
        if resource_schema is not None:
            inherited = getattr(cls, 'resource_schema', {})
            resource_schema.update(inherited)
            cls.resource_schema = resource_schema
        cls.extended_fields = cls.resource_fields
        cls.compact_fields = [
            n for n in cls.extended_fields
            if mcs.include_field_for_compact(cls, n)] + ['resource']
        cls.build_resource_schema()
        return cls


class ResourceModel(db.Model, metaclass=BaseResource):
    resource_fields = ['id']
    identifiers = []
    resource_schema = {'id': {'readonly': True}}

    id = db.CharField(max_length=50, unique=True, null=False)

    class Meta:
        manager = SelectQuery
        validator = ResourceValidator

    @classmethod
    def make_id(cls):
        return 'ban-{}-{}'.format(cls.__name__.lower(), uuid.uuid4().hex)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = self.make_id()
        return super().save(*args, **kwargs)

    @classmethod
    def build_resource_schema(cls):
        """Map Peewee models to Cerberus validation schema."""
        schema = dict(cls.resource_schema)
        for name, field in cls._meta.fields.items():
            if name not in cls.extended_fields:
                continue
            if field.primary_key:
                continue
            type_ = getattr(field.__class__, 'schema_type', None)
            if not type_:
                continue
            row = {
                'type': type_,
                'required': not field.null,
                'coerce': field.coerce,
            }
            if field.null:
                row['nullable'] = True
            if field.unique:
                row['unique'] = True
            max_length = getattr(field, 'max_length', None)
            if max_length:
                row['maxlength'] = max_length
            if not field.null:
                row['empty'] = False
            if getattr(field, 'choices', None):
                row['allowed'] = [v for v, l in field.choices]
            row.update(cls.resource_schema.get(name, {}))
            schema[name] = row
            if schema[name].get('readonly'):
                schema[name]['required'] = False
        cls.resource_schema = schema

    @classmethod
    def validator(cls, instance=None, update=False, **data):
        validator = cls._meta.validator(cls)
        validator(data, update=update, instance=instance)
        return validator

    @property
    def resource(self):
        return self.__class__.__name__.lower()

    @property
    def as_resource(self):
        """Resource plus relations."""
        return {f: self.extended_field(f) for f in self.extended_fields}

    @property
    def as_relation(self):
        """Resources plus relation references without metadata."""
        return {f: self.compact_field(f) for f in self.compact_fields}

    @property
    def as_version(self):
        """Resources plus relations references and metadata."""
        return {f: self.compact_field(f) for f in self.extended_fields}

    def extended_field(self, name):
        value = getattr(self, '{}_extended'.format(name), getattr(self, name))
        return getattr(value, 'as_relation', value)

    def compact_field(self, name):
        value = getattr(self, '{}_compact'.format(name), getattr(self, name))
        return getattr(value, 'id', value)

    @classmethod
    def coerce(cls, id, identifier=None):
        if not identifier:
            identifier = 'id'  # BAN id by default.
            if isinstance(id, str):
                *extra, id = id.split(':')
                if extra:
                    identifier = extra[0]
                if identifier not in cls.identifiers + ['id', 'pk']:
                    raise cls.DoesNotExist("Invalid identifier {}".format(
                                                                identifier))
        try:
            return cls.get(getattr(cls, identifier) == id)
        except cls.DoesNotExist:
            # Is it an old identifier?
            from .versioning import IdentifierRedirect
            new = IdentifierRedirect.follow(cls, identifier, id)
            if new:
                return cls.get(getattr(cls, identifier) == new)
            else:
                raise
