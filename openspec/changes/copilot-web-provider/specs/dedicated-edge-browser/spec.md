# Spec Delta

## Purpose

Garantiza que el harness solo automatiza un Edge con un perfil dedicado a él, que el login lo hace siempre una persona, que nunca hay dos navegadores sobre el mismo perfil y que, pase lo que pase, solo cierra lo que él abrió.

## ADDED Requirements

### Requirement: Solo un perfil dedicado
El sistema SHALL abrir Edge únicamente con el directorio de perfil configurado para el harness. SHALL aceptar ese directorio solo si no existe, está vacío o contiene la marca de perfil del harness, y SHALL rechazar cualquier otro directorio sin abrir el navegador.

#### Scenario: Perfil nuevo
- **WHEN** el directorio de perfil configurado no existe y el usuario ejecuta `copilot login`
- **THEN** el sistema crea el directorio con la marca de perfil del harness y abre Edge con él

#### Scenario: Directorio de perfil ajeno
- **WHEN** el directorio de perfil configurado contiene ficheros y no tiene la marca del harness
- **THEN** el sistema termina con código distinto de 0, explica que no es un perfil del harness y no abre el navegador

### Requirement: Login manual
El comando `copilot login` SHALL abrir Edge visible con el perfil dedicado en la URL de Copilot configurada y SHALL esperar a que la persona termine, sin rellenar, pulsar ni leer campos de la página. SHALL terminar con código 0 si al final la página está lista para preguntar y con código distinto de 0 si no.

#### Scenario: Login completado a mano
- **WHEN** Wilson inicia sesión a mano y la página llega a estar lista para preguntar
- **THEN** `copilot login` cierra el navegador y termina con código 0

#### Scenario: Ventana cerrada sin iniciar sesión
- **WHEN** Wilson cierra la ventana sin haber iniciado sesión
- **THEN** `copilot login` termina con código distinto de 0 e indica que no hay sesión iniciada

#### Scenario: Ningún campo tocado durante el login
- **WHEN** `copilot login` se ejecuta contra una página de login sintética que registra pulsaciones y clics, y la prueba cierra la ventana
- **THEN** la página registra cero pulsaciones y cero clics del harness

### Requirement: Portada de invitado en la URL configurada
Una página del host configurado que ofrece iniciar sesión SHALL NOT contar como lista. `copilot login` SHALL guardar en el directorio de datos solo la forma de la ruta donde Copilot quedó listo (su primer segmento, si es una palabra simple) y, si no es la ruta configurada y la URL configurada lleva a una página que ofrece iniciar sesión, SHALL terminar con código distinto de 0 con un mensaje que diga que la sesión quedó guardada y proponga esa ruta.

#### Scenario: La URL configurada lleva a la portada de invitado
- **WHEN** la URL configurada es una portada sintética que ofrece iniciar sesión y Wilson abre a mano el chat, donde la página queda lista
- **THEN** `copilot login` termina con código distinto de 0, dice que la sesión quedó guardada y que la URL lleva a la portada de invitado, propone la ruta del chat como `HARNESS_COPILOT_URL` y no escribe en ninguna de las dos páginas

### Requirement: Un solo navegador a la vez
El sistema SHALL tener como máximo un Edge abierto sobre el perfil dedicado en todo el equipo. Una pregunta que encuentra el navegador ocupado por otro proceso SHALL esperar su turno dentro de su plazo, y si el plazo vence esperando SHALL terminar en `timeout` sin envío. `copilot login` con el navegador ocupado SHALL terminar con código distinto de 0 sin esperar.

#### Scenario: Dos sesiones preguntan a la vez
- **WHEN** dos procesos preguntan a la vez en dos sesiones distintas de `copilot_web`
- **THEN** las dos solicitudes terminan en `completed` y en ningún momento hay dos navegadores abiertos sobre el perfil

#### Scenario: Turno que no llega
- **WHEN** un proceso tiene el navegador ocupado más tiempo que el plazo de otra pregunta
- **THEN** la segunda solicitud queda en `timeout` y su página no ha recibido ningún prompt

#### Scenario: Login con el navegador ocupado
- **WHEN** una pregunta tiene el navegador abierto y el usuario ejecuta `copilot login`
- **THEN** `copilot login` termina con código distinto de 0 indicando que el navegador está en uso

### Requirement: Solo se liberan recursos propios
Al terminar una pregunta, con éxito, con error, por plazo, por Ctrl+C o por caída del navegador, el sistema SHALL cerrar el navegador que abrió y SHALL NOT cerrar ni afectar a ningún otro proceso de Edge del usuario.

#### Scenario: Navegador del usuario intacto
- **WHEN** hay otro Edge abierto con otro perfil y una pregunta del harness termina por caída de su propio navegador
- **THEN** el otro Edge sigue en ejecución

#### Scenario: Nada queda abierto tras un plazo vencido
- **WHEN** una pregunta termina en `uncertain` por plazo vencido
- **THEN** al terminar el proceso no queda ningún navegador abierto sobre el perfil dedicado y la siguiente pregunta puede abrirlo

#### Scenario: Proceso del harness matado
- **WHEN** el proceso de `ask` muere sin poder limpiar mientras su navegador está abierto
- **THEN** la siguiente pregunta obtiene el navegador o informa de forma controlada de que el perfil sigue en uso, sin traza de excepción
