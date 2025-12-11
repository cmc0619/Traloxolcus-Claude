# System Architecture

Multi-Camera Soccer Recording System architecture documentation.

## High-Level Overview

```mermaid
flowchart TB
    subgraph FIELD["Soccer Field"]
        CAM_L[Pi Camera 1<br/>Left]
        CAM_C[Pi Camera 2<br/>Center]
        CAM_R[Pi Camera 3<br/>Right]
    end

    subgraph HOME["Home Server (GPU)"]
        INGEST[Ingest Server]
        STITCH[Video Stitcher<br/>CUDA/FFmpeg]
        ML[ML Pipeline<br/>YOLO + Pose]
        PUSH[Push Service]
    end

    subgraph CLOUD["VPS (Viewer Server)"]
        NGINX[Nginx<br/>SSL/HTTPS]
        FLASK[Flask App]
        CELERY[Celery Worker]
        PG[(PostgreSQL)]
        REDIS[(Redis)]
    end

    subgraph USERS["End Users"]
        PARENT[Parents]
        COACH[Coaches]
    end

    subgraph EXTERNAL["External Services"]
        TS[TeamSnap API]
        SMTP[Email SMTP]
    end

    CAM_L & CAM_C & CAM_R -->|Upload| INGEST
    INGEST --> STITCH
    STITCH --> ML
    ML --> PUSH
    PUSH -->|Video + Metadata| NGINX

    NGINX --> FLASK
    FLASK <--> PG
    FLASK <--> REDIS
    REDIS <--> CELERY
    CELERY --> SMTP

    FLASK <-->|OAuth| TS
    PARENT & COACH -->|View| NGINX
    SMTP -->|Notifications| PARENT
```

## Component Details

### Camera Nodes (Raspberry Pi 5)

```mermaid
flowchart LR
    subgraph PI["Pi Camera Node"]
        CAM[Camera Module<br/>4K Sensor]
        REC[Camera Recorder<br/>H.264/H.265]
        STORE[Storage Manager<br/>Local SSD]
        API[API Server<br/>:8080]
        SYNC[Sync Manager<br/>NTP]
        OFF[Offload Client]
        PREV[Preview Server<br/>MJPEG]
        AUDIO[Audio Feedback]
    end

    CAM --> REC --> STORE
    STORE --> OFF
    API --> REC
    SYNC --> REC
    STORE --> PREV
    API --> AUDIO
```

### Processing Server Pipeline

```mermaid
flowchart TD
    subgraph PROC["Processing Pipeline"]
        IN[Ingest Server<br/>Chunked Upload]
        VAL[Validation<br/>Checksum]
        STITCH[Video Stitcher<br/>GPU Accelerated]
        DET[Object Detection<br/>YOLOv8]
        POSE[Pose Estimation<br/>Player Tracking]
        EVENT[Event Classification<br/>Goals/Saves/Shots]
        CLIP[Clip Generator<br/>Highlights]
        PUSH[Push Service<br/>rsync/S3]
    end

    IN --> VAL --> STITCH
    STITCH --> DET --> POSE --> EVENT
    EVENT --> CLIP
    CLIP --> PUSH
    EVENT --> PUSH
```

### Viewer Server Services

```mermaid
flowchart TB
    subgraph VIEWER["Viewer Server"]
        subgraph WEB["Web Layer"]
            NG[Nginx<br/>SSL Termination]
            FL[Flask App<br/>REST API]
            JINJA[Jinja Templates]
        end

        subgraph SERVICES["Services"]
            STATS[Statistics Service<br/>Aggregation]
            HEAT[HeatMap Service<br/>Position Viz]
            DEMO[Demo Data<br/>Generator]
        end

        subgraph INTEGRATIONS["Integrations"]
            TSNAP[TeamSnap<br/>OAuth + Roster]
            EMAIL[Email Service<br/>Notifications]
        end

        subgraph AUTH["Authentication"]
            ADMIN[Admin Portal<br/>Config]
            PARENT[Parent Portal<br/>Login/Dashboard]
        end

        subgraph DATA["Data Layer"]
            PG[(PostgreSQL)]
            RD[(Redis)]
            CEL[Celery Workers]
        end
    end

    NG --> FL --> JINJA
    FL --> STATS & HEAT & DEMO
    FL --> TSNAP & EMAIL
    FL --> ADMIN & PARENT
    FL <--> PG
    FL <--> RD
    RD <--> CEL
    CEL --> EMAIL
```

## Database Schema

```mermaid
erDiagram
    User ||--o{ parent_player : has
    User ||--o{ team_coach : coaches
    User {
        int id PK
        string email UK
        string password_hash
        string first_name
        string last_name
        enum role
        enum notify_frequency
    }

    Player ||--o{ parent_player : belongs
    Player ||--o{ team_player : plays
    Player ||--o{ GameEvent : generates
    Player ||--o{ PlayerGameStats : has
    Player {
        int id PK
        string first_name
        string last_name
        int birth_year
        enum default_position
    }

    Organization ||--o{ Team : owns
    Organization {
        int id PK
        string name
        string slug UK
    }

    Team ||--o{ team_player : has
    Team ||--o{ team_coach : managed_by
    Team ||--o{ Game : plays
    Team {
        int id PK
        int organization_id FK
        string name
        int birth_year_start
        string season
    }

    Game ||--o{ GameEvent : contains
    Game ||--o{ Clip : generates
    Game ||--o{ PlayerGameStats : produces
    Game {
        int id PK
        int team_id FK
        string opponent
        datetime game_date
        int home_score
        int away_score
        boolean is_processed
    }

    GameEvent ||--o{ Clip : triggers
    GameEvent {
        int id PK
        int game_id FK
        int player_id FK
        enum event_type
        float timestamp_seconds
        float confidence
        float field_position_x
        float field_position_y
    }

    parent_player {
        int parent_id FK
        int player_id FK
        string relationship
    }

    team_player {
        int team_id FK
        int player_id FK
        string jersey_number
    }
```

## Data Flow Sequences

### Recording Session

```mermaid
sequenceDiagram
    participant CAM as Camera Nodes
    participant PROC as Processing Server
    participant VIEW as Viewer Server
    participant DB as Database
    participant PARENT as Parent

    Note over CAM: Game Recording
    CAM->>CAM: Record 3 camera streams
    CAM->>CAM: Local storage
    CAM->>PROC: Upload video chunks
    PROC->>PROC: Validate checksums
    PROC->>PROC: Stitch panorama
    PROC->>PROC: ML detection
    PROC->>VIEW: Push video + metadata
    VIEW->>DB: Store game/events
    VIEW->>VIEW: Generate clips
    VIEW->>PARENT: Email notification
```

### TeamSnap Integration

```mermaid
sequenceDiagram
    participant P as Parent
    participant V as Viewer Server
    participant TS as TeamSnap API
    participant DB as Database

    P->>V: Connect TeamSnap
    V->>TS: OAuth redirect
    P->>TS: Authorize
    TS->>V: Access token
    V->>TS: Fetch teams
    V->>TS: Fetch rosters
    V->>DB: Create/update teams
    V->>DB: Link players to parent
    V->>P: Dashboard ready
```

### Notification Flow

```mermaid
sequenceDiagram
    participant ML as ML Pipeline
    participant DB as Database
    participant CEL as Celery Worker
    participant SMTP as Email Service
    participant P as Parent

    ML->>DB: Save goal event
    DB->>CEL: Trigger notification
    CEL->>DB: Check parent prefs
    alt Instant notifications
        CEL->>SMTP: Send email now
        SMTP->>P: Goal alert
    else Daily digest
        CEL->>DB: Queue for digest
    end
```

## Deployment Architecture

```mermaid
flowchart TB
    subgraph DOCKER["Docker Compose"]
        subgraph viewer["Viewer Container"]
            nginx[Nginx]
            flask[Flask + Gunicorn]
        end

        subgraph processing["Processing Container"]
            proc[Processing Server]
            gpu[NVIDIA GPU]
        end

        subgraph data["Data Containers"]
            pg[(PostgreSQL)]
            redis[(Redis)]
        end

        subgraph workers["Worker Container"]
            celery[Celery Worker]
        end
    end

    subgraph storage["Persistent Storage"]
        vol_pg[(postgres_data)]
        vol_vid[(video_storage)]
        vol_ssl[(ssl_certs)]
    end

    nginx --> flask
    flask --> pg & redis
    redis --> celery
    proc -.-> gpu
    proc --> flask

    pg --> vol_pg
    flask --> vol_vid
    nginx --> vol_ssl
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Camera Hardware** | Raspberry Pi 5 + 4K Camera Module |
| **Camera Software** | Python, picamera2, Flask |
| **Processing** | Python, CUDA, OpenCV, YOLOv8, FFmpeg |
| **Web Server** | Nginx + SSL, Flask + Gunicorn |
| **Database** | PostgreSQL + SQLAlchemy ORM |
| **Task Queue** | Redis + Celery |
| **Containerization** | Docker + Docker Compose |
| **External APIs** | TeamSnap OAuth, SMTP |

## Key Directories

```
Traloxolcus-Claude/
├── src/soccer_rig/           # Camera node code
│   ├── camera/               # Video recording
│   ├── coordinator/          # Multi-camera sync
│   └── offload/              # Upload to processing
├── processing-server/        # Home GPU server
│   └── src/processing_server/
│       ├── ingest/           # Receive uploads
│       ├── stitcher/         # Video stitching
│       ├── ml/               # YOLO detection
│       └── push/             # Sync to viewer
├── soccer-rig-server/        # Viewer server (VPS)
│   └── src/
│       ├── models.py         # Database schema
│       ├── services/         # Stats, heatmaps
│       ├── integrations/     # TeamSnap, email
│       ├── admin.py          # Admin portal
│       └── parent_portal.py  # Parent dashboard
└── docker-compose.yml        # Deployment config
```
