# Grande Auto Hut — Backend

Backend API for **Grande Auto Hut**, an auto-parts e-commerce platform. Built with **Django** and **Django REST Framework**, it handles product catalog and vehicle fitment, inventory, orders, payments, reviews, customer support, and notifications, exposed through a documented REST API.


## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Database Setup](#database-setup)
  - [Running the Server](#running-the-server)
- [API Documentation](#api-documentation)
- [App Overview](#app-overview)
- [Authentication](#authentication)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)


## Features

-  JWT-based authentication and account management
-  Product catalog with categories and search/filtering
-  Vehicle **fitment** lookup (find parts compatible with a specific vehicle)
-  Inventory tracking and stock management
-  Order creation and lifecycle management
-  Payment processing integration
-  Product reviews and ratings
-  Notifications for order/account events
-  Customer support ticketing
-  Auto-generated, interactive API documentation (OpenAPI schema)

## Tech Stack

| Layer | Technology |
|---|---|
| Language / Framework | Python, Django |
| API | Django REST Framework (DRF) |
| Authentication | djangorestframework-simplejwt (JWT) |
| API Schema/Docs | drf-spectacular (OpenAPI 3) |
| Database | PostgreSQL (via `psycopg2-binary`, `dj-database-url`) |
| Filtering | django-filter |
| Static Files | WhiteNoise |
| CORS | django-cors-headers |
| Image Handling | Pillow |
| WSGI Server | Gunicorn |
| Config Management | python-decouple, python-dotenv |
| Deployment | Render |

## Project Structure

```
grande-auto-hut-backend/
├── accounts/          # User accounts, authentication, profiles
├── auto_project/      # Django project settings, root URLs, WSGI/ASGI entry points
├── catalog/           # Products, categories, product listings
├── core/              # Shared/base utilities used across apps
├── fitment/           # Vehicle make/model/year to part compatibility
├── inventory/         # Stock levels and inventory management
├── notifications/     # Notification triggers and delivery
├── orders/            # Cart, checkout, and order lifecycle
├── payments/          # Payment processing and transaction records
├── reviews/           # Product ratings and customer reviews
├── support/           # Customer support tickets/inquiries
├── manage.py          # Django management entry point
├── requirements.txt   # Python dependencies
└── LICENSE
```

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL (running locally or accessible remotely)
- pip / virtualenv

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/JeromeJason-dev/grande-auto-hut-backend.git
   cd grande-auto-hut-backend
   ```

2. **Create and activate a virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate      # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

### Environment Variables

Create a `.env` file in the project root. At minimum, the following variables are typically required for a project of this shape:

```env
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgres://user:password@localhost:5432/grande_auto_hut

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:3000

# Payments (if applicable to your provider)
PAYMENT_SECRET_KEY=your-payment-provider-secret-key
```

> ⚠️ Confirm the exact variable names against `auto_project/settings.py`, since this list is based on the packages used (`python-decouple`, `dj-database-url`, `django-cors-headers`) rather than the settings file itself.

### Database Setup

Run migrations to set up the database schema:

```bash
python manage.py makemigrations
python manage.py migrate
```

Create a superuser to access the Django admin:

```bash
python manage.py createsuperuser
```

### Running the Server

```bash
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/`.

## API Documentation

This project uses **drf-spectacular** to auto-generate an OpenAPI 3 schema. Once the server is running, documentation is typically available at:

- Schema: `/api/schema/`
- Swagger UI: `/api/docs/`
- Redoc: `/api/redoc/`

> Exact paths depend on how they're wired up in `auto_project/urls.py`.

## App Overview

| App | Responsibility |
|---|---|
| `accounts` | User registration, login, profile management |
| `catalog` | Products and categories |
| `fitment` | Vehicle-to-part compatibility matching |
| `inventory` | Stock levels and availability |
| `orders` | Shopping cart and order processing |
| `payments` | Payment transactions |
| `reviews` | Customer product reviews and ratings |
| `notifications` | User-facing notifications |
| `support` | Support tickets and customer inquiries |
| `core` | Shared utilities/helpers |
| `auto_project` | Project-level settings and configuration |

## Authentication

The API uses **JWT authentication** via `djangorestframework-simplejwt`. Typical flow:


Include the access token in subsequent requests:

```
Authorization: Bearer <access_token>
```

## Deployment

The project is configured for deployment with **Gunicorn** and **WhiteNoise** for static file serving, and is currently deployed on **Render** 

Typical production steps:

```bash
python manage.py collectstatic --noinput
gunicorn auto_project.wsgi:application
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

## License

This project is licensed under the **MIT License**.