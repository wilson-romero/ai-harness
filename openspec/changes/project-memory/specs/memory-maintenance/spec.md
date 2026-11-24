# Spec Delta

## Purpose

Da al usuario un informe reproducible de lo que un mantenimiento del vault encontraría y propondría, sin modificar el vault, como paso previo al curador y al Sueño del Corte 8.

## ADDED Requirements

### Requirement: Solo modo de prueba
`memory maintain` SHALL exigir `--dry-run`. Sin esa opción SHALL terminar con un error controlado sin leer el vault.

#### Scenario: Sin --dry-run
- **WHEN** el usuario ejecuta `memory maintain`
- **THEN** el sistema informa de que en este corte solo existe `--dry-run` y termina con código distinto de 0

### Requirement: Hallazgos del informe
El informe SHALL listar, por categoría y con su recuento: ficheros de conflicto de sincronización que se pondrían en cuarentena, enlaces `[[...]]` rotos con su corrección inequívoca si existe, entradas colgantes y notas sin entrada en los índices `MEMORY*.md` de `Memoria-CC/`, candidatos a duplicado por nombre, notas sin frontmatter válido, notas con credenciales de formato conocido y entradas ignoradas por la lectura confinada.

#### Scenario: Vault sintético con defectos plantados
- **WHEN** el vault sintético contiene un fichero `.sync-conflict-`, un enlace roto con un único candidato, una nota fuera del índice, una nota sin frontmatter y un enlace simbólico hacia fuera
- **THEN** cada defecto aparece en su categoría con recuento 1

#### Scenario: Vault limpio
- **WHEN** el vault no tiene ninguno de esos defectos
- **THEN** todas las categorías aparecen con recuento 0 y el código de salida es 0

### Requirement: El informe no expone contenido
El informe SHALL nombrar rutas relativas y tipos de hallazgo, y SHALL NOT incluir el valor de una credencial ni fragmentos del cuerpo de las notas.

#### Scenario: Credencial detectada sin mostrarla
- **WHEN** una nota contiene un token con formato conocido
- **THEN** el informe lista esa ruta y el tipo de credencial, y la salida no contiene el token

### Requirement: Informe determinista y sin escrituras
Dos ejecuciones sobre el mismo vault SHALL producir el mismo informe byte a byte, y ninguna SHALL crear, modificar, mover ni borrar nada en el vault.

#### Scenario: Dos ejecuciones idénticas
- **WHEN** el usuario ejecuta `memory maintain --dry-run` dos veces seguidas
- **THEN** las dos salidas son idénticas

#### Scenario: Vault intacto
- **WHEN** termina `memory maintain --dry-run` sobre el vault sintético con defectos plantados
- **THEN** la huella del vault (rutas, tamaños, fechas de modificación y hashes) es idéntica a la de antes
