-- CREATE EXTENSION postgis;
--
-- CREATE schema public;

CREATE ROLE brat_data_steward LOGIN PASSWORD '%5KFx$WRp4W#';

CREATE TABLE epochs (
  epoch_id      INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  name          VARCHAR(50) UNIQUE NOT NULL,
  metadata      VARCHAR(10) UNIQUE NOT NULL,
  notes         TEXT
);

CREATE TABLE land_uses (
    land_use_id INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name        VARCHAR(255) UNIQUE NOT NULL,
    intensity   REAL NOT NULL DEFAULT 0

    CONSTRAINT ck_land_uses_intensity CHECK ((intensity >= 0) AND (intensity <= 1))
);

CREATE TABLE vegetation_types (
    vegetation_id   INT NOT NULL PRIMARY KEY,
    epoch_id        INT NOT NULL,
    name            VARCHAR(100),
    default_suitability SMALLINT NOT NULL,
    land_use_id         INT,
    physiognomy         VARCHAR(255),
    notes               TEXT,

    CONSTRAINT fk_vegetation_types_epoch_id FOREIGN KEY (epoch_id) REFERENCES epochs(epoch_id),
    CONSTRAINT fk_vegetation_types_land_use_id FOREIGN KEY (land_use_id) REFERENCES land_uses(land_use_id),

    CONSTRAINT ck_vegetation_types_default_suitability CHECK ((default_suitability >= 0) AND (default_suitability <= 4))
);
CREATE INDEX fx_vegetation_types_epoch_id ON vegetation_types(epoch_id);
CREATE INDEX fx_vegetation_types_land_use_id ON vegetation_types(land_use_id);

CREATE TABLE ecoregions (
    ecoregion_id        INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name                VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE vegetation_overrides (
    ecoregion_id            INT NOT NULL,
    vegetation_id           INT NOT NULL,
    override_suitability    SMALLINT NOT NULL,
    notes                   TEXT,

    CONSTRAINT pk_vegetation_overrides PRIMARY KEY (ecoregion_id, vegetation_id),
    CONSTRAINT fk_vegetation_overrides_ecoregion_id FOREIGN KEY (ecoregion_id) REFERENCES ecoregions(ecoregion_id),
    CONSTRAINT fk_vegetation_overrides_vegetation_id FOREIGN KEY (vegetation_id) REFERENCES vegetation_types(vegetation_id),
    CONSTRAINT ck_vegetation_overrides_override_suitability CHECK ((override_suitability >= 0) AND (override_suitability <= 4))
);
CREATE INDEX fx_vegetation_overrides_ecoregion_id ON vegetation_overrides(ecoregion_id);
CREATE INDEX fx_vegetation_overrides_vegetation_id ON vegetation_overrides(vegetation_id);

CREATE TABLE hydro_params (
    param_id                INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name                    VARCHAR(255) UNIQUE NOT NULL,
    description             TEXT,
    aliases                 TEXT,
    data_units              VARCHAR(255) NOT NULL,
    equation_units          VARCHAR(255) NOT NULL,
    conversion              REAL NOT NULL DEFAULT 1,
    definition              TEXT
);

CREATE TABLE watersheds (
    watershed_id            VARCHAR(8) NOT NULL PRIMARY KEY,
    name                    VARCHAR(255),
    area_sqkm                REAL,
    states                  VARCHAR(50),
    geometry                TEXT,
    qlow                    VARCHAR(255),
    q2                      VARCHAR(255),
    max_drainage            REAL,
    ecoregion_id            INT,
    notes                   TEXT,
    metadata                TEXT,

    CONSTRAINT fk_watersheds_ecoregion_id FOREIGN KEY (ecoregion_id) REFERENCES ecoregions(ecoregion_id)
);
CREATE INDEX fx_watersheds_ecoregion_id ON watersheds(ecoregion_id);

CREATE TABLE watershed_hydro_params (
    watershed_id             VARCHAR(8) NOT NULL,
    param_id                 INT NOT NULL,
    value                    REAL,

    CONSTRAINT pk_watesrhed_hydro_params PRIMARY KEY (watershed_id, param_id),
    CONSTRAINT fk_watershed_hydro_params_watershed_id FOREIGN KEY (watershed_id) REFERENCES watersheds(watershed_id),
    CONSTRAINT fk_watershed_hydro_params_param_id FOREIGN KEY (param_id) REFERENCES hydro_params(param_id)
);

CREATE INDEX fx_watershed_hydro_params_watershed_id ON watershed_hydro_params(watershed_id);
CREATE INDEX fx_watershed_hydro_params_param_id ON watershed_hydro_params(param_id);

CREATE VIEW vw_watershed_hydro_params AS
(
SELECT whp.watershed_id, p.name, whp.value, p.data_units, p.equation_units, p.conversion
FROM hydro_params p
         INNER JOIN watershed_hydro_params whp on p.param_id = whp.param_id
    );

CREATE TABLE project_types (
    project_types_id INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    project_type_name Varchar(255) UNIQUE NOT NULL
);

CREATE TABLE project_bounds (
    project_id INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
	project_guid Varchar(255) UNIQUE,
	project_name Varchar(255),
	project_type_id int,
	centroid Geography(point),
	bounding_box Geography(polygon),
	extent Geography(polygon),
	metadata jsonb,
	CONSTRAINT fk_project_bounds_project_type_id FOREIGN KEY (project_type_id) REFERENCES project_types(project_types_id)
);

CREATE INDEX gx_project_bounds_centroid on project_bounds USING GIST (centroid);
CREATE INDEX gx_project_bounds_bounding_box on project_bounds USING GIST (bounding_box);
CREATE INDEX gx_project_bounds_extent on project_bounds USING GIST (extent);

CREATE INDEX fx_project_bounds_project_type_id ON
project_bounds(project_type_id);
GRANT SELECT, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public TO brat_data_steward;
GRANT INSERT, UPDATE, DELETE ON vegetation_overrides TO brat_data_steward;
GRANT INSERT, UPDATE, DELETE ON hydro_params TO brat_data_steward;
GRANT INSERT, UPDATE, DELETE ON watershed_hydro_params TO brat_data_steward;
GRANT UPDATE (default_suitability, notes) ON public.vegetation_types TO brat_data_steward;
GRANT UPDATE (q2,qlow,max_drainage, notes, ecoregion_id, metadata) ON watersheds TO brat_data_steward;