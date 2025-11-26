from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wafer_space.projects"
    verbose_name = "Projects"

    def ready(self) -> None:
        """Initialize app - register content processors.

        Import processors and register with global registry.
        Local imports are standard Django pattern for ready() to avoid
        import-time side effects.
        """
        # Import registry
        from wafer_space.projects.content_processors import (  # noqa: PLC0415
            _processor_registry,
        )

        # Import decompressor classes
        from wafer_space.projects.processors.decompressors import (  # noqa: PLC0415
            Bzip2Decompressor,
        )
        from wafer_space.projects.processors.decompressors import (  # noqa: PLC0415
            GzipDecompressor,
        )
        from wafer_space.projects.processors.decompressors import (  # noqa: PLC0415
            XzDecompressor,
        )

        # Import extractor classes
        from wafer_space.projects.processors.extractors import (  # noqa: PLC0415
            TarExtractor,
        )
        from wafer_space.projects.processors.extractors import (  # noqa: PLC0415
            ZipExtractor,
        )

        # Register all processors
        _processor_registry.register(GzipDecompressor())
        _processor_registry.register(Bzip2Decompressor())
        _processor_registry.register(XzDecompressor())
        _processor_registry.register(ZipExtractor())
        _processor_registry.register(TarExtractor())
