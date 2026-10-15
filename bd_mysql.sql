-- IndieVault - modelo fisico en MySQL
-- Traducido desde bd.txt (Oracle Database 11g / SQL Developer Data Modeler)
-- Dialecto: MySQL 8.x (InnoDB, utf8mb4)

DROP DATABASE IF EXISTS indievault;
CREATE DATABASE indievault
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
USE indievault;

-- Oracle VARCHAR2(n) -> VARCHAR(n) | NUMBER -> INT o DECIMAL | DATE -> DATE
-- PK NUMBER sin secuencia -> INT AUTO_INCREMENT (equivalente al SEQUENCE de Oracle)

CREATE TABLE GENERO (
    id_genero     INT NOT NULL AUTO_INCREMENT,
    nombre_genero VARCHAR(50) NOT NULL,
    CONSTRAINT GENERO_PK PRIMARY KEY (id_genero)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE Usuario (
    id_usuario     INT NOT NULL AUTO_INCREMENT,
    username       VARCHAR(50) NOT NULL,
    email          VARCHAR(100) NOT NULL,
    password       VARCHAR(225) NOT NULL,
    fecha_registro DATE NOT NULL,
    CONSTRAINT Usuario_PK PRIMARY KEY (id_usuario)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE DESARROLLADOR (
    id_desarrollador   INT NOT NULL AUTO_INCREMENT,
    nombre_estudio     VARCHAR(100) NOT NULL,
    sitio_web          VARCHAR(150) NULL,
    Usuario_id_usuario INT NOT NULL,
    CONSTRAINT DESARROLLADOR_PK PRIMARY KEY (id_desarrollador),
    CONSTRAINT DESARROLLADOR_Usuario_FK FOREIGN KEY (Usuario_id_usuario)
        REFERENCES Usuario (id_usuario)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE JUEGO (
    id_juego                       INT NOT NULL AUTO_INCREMENT,
    titulo                         VARCHAR(100) NOT NULL,
    descripcion                    VARCHAR(500) NOT NULL,
    precio                         DECIMAL(10,2) NOT NULL,
    fecha_lanzamiento              DATE NULL,
    DESARROLLADOR_id_desarrollador INT NOT NULL,
    CONSTRAINT JUEGO_PK PRIMARY KEY (id_juego),
    CONSTRAINT JUEGO_DESARROLLADOR_FK FOREIGN KEY (DESARROLLADOR_id_desarrollador)
        REFERENCES DESARROLLADOR (id_desarrollador)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE COMPRA (
    id_compra          INT NOT NULL AUTO_INCREMENT,
    fecha_compra       DATE NOT NULL,
    monto              DECIMAL(10,2) NOT NULL,
    Usuario_id_usuario INT NOT NULL,
    JUEGO_id_juego     INT NOT NULL,
    CONSTRAINT COMPRA_PK PRIMARY KEY (id_compra),
    CONSTRAINT COMPRA_JUEGO_FK FOREIGN KEY (JUEGO_id_juego)
        REFERENCES JUEGO (id_juego),
    CONSTRAINT COMPRA_Usuario_FK FOREIGN KEY (Usuario_id_usuario)
        REFERENCES Usuario (id_usuario)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE JUEGO_GENERO (
    id_juego_genero  INT NOT NULL,
    JUEGO_id_juego   INT NOT NULL,
    GENERO_id_genero INT NOT NULL,
    CONSTRAINT JUEGO_GENERO_PK PRIMARY KEY (id_juego_genero, JUEGO_id_juego),
    CONSTRAINT JUEGO_GENERO_JUEGO_FK FOREIGN KEY (JUEGO_id_juego)
        REFERENCES JUEGO (id_juego),
    CONSTRAINT JUEGO_GENERO_GENERO_FK FOREIGN KEY (GENERO_id_genero)
        REFERENCES GENERO (id_genero)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
