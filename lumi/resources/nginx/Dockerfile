FROM nginx:latest

RUN rm /etc/nginx/conf.d/default.conf
COPY ./default.conf /etc/nginx/conf.d/

# Create React App at /setup: copy your CRA build into html/setup/
# Example: COPY ./path-to-your-cra-build/ /usr/share/nginx/html/setup/
# Or mount at run: -v /path/to/build:/usr/share/nginx/html/setup:ro
RUN mkdir -p /usr/share/nginx/html/setup
