import numpy as np
import os
import json
import sys

#### function to do mobility and update the node location for each tau ####
def do_mobility(node, room_length, room_width, tau):

    mobility_type = node['mobility'].get('type', 'static')
    speed = node['mobility'].get('speed', 0.0)
    location = np.array(node['location'])


    ### static mobility ###

    if mobility_type == "static":
        return node['location']
    

    ### 2d(z coordinate is fixed) random walk mobility ###

    elif mobility_type == "random_walk":
        theta = np.random.uniform(0, 2 * np.pi)
        dx = np.cos(theta) * speed * tau
        dy = np.sin(theta) * speed * tau
        
        new_location = location + np.array([dx, dy, 0])
        
        new_location[0] = min(max(0, new_location[0]), room_length)
        new_location[1] = min(max(0, new_location[1]), room_width)
        
        return new_location.tolist()
    

    ### 2d random waypoint (z coordinate is fixed) mobility ###

    elif mobility_type == "random_waypoint":
        if 'waypoint' not in node['mobility'] or node['mobility']['waypoint'] is None:
            wp_x = np.random.uniform(0, room_length)
            wp_y = np.random.uniform(0, room_width)
            # FIX: Convert waypoint coordinates to standard Python floats
            node['mobility']['waypoint'] = [float(wp_x), float(wp_y), float(location[2])]

        waypoint = np.array(node['mobility']['waypoint'])
        direction = waypoint - location
        distance_to_waypoint = np.linalg.norm(direction)

        if distance_to_waypoint < speed * tau:
            new_location = waypoint
            node['mobility']['waypoint'] = None
        else:
            direction /= distance_to_waypoint
            new_location = location + direction * speed * tau

        new_location[0] = min(max(0, new_location[0]), room_length)
        new_location[1] = min(max(0, new_location[1]), room_width)

        return new_location.tolist()
    


     ### 2d random direction (z coordinate is fixed) mobility ###

    elif mobility_type == "random_direction":
        if 'direction_vector' not in node['mobility'] or node['mobility']['direction_vector'] is None:
            theta = np.random.uniform(0, 2 * np.pi)
            dx = np.cos(theta)
            dy = np.sin(theta)
            # FIX: Convert direction vector to standard Python floats
            node['mobility']['direction_vector'] = [float(dx), float(dy), 0.0]

        direction_vector = np.array(node['mobility']['direction_vector'])
        movement = direction_vector * speed * tau
        new_location = location + movement
        
        hit_boundary = False
        if not (0 <= new_location[0] <= room_length):
            hit_boundary = True
            new_location[0] = min(max(0, new_location[0]), room_length)
        if not (0 <= new_location[1] <= room_width):
            hit_boundary = True
            new_location[1] = min(max(0, new_location[1]), room_width)

        if hit_boundary:
            node['mobility']['direction_vector'] = None

        return new_location.tolist()
    


     ### 2d gauss markov (z coordinate is fixed) mobility ###

    elif mobility_type == "gauss_markov":
        alpha = node['mobility'].get('alpha', 0.75)
        mean_speed = node['mobility'].get('mean_speed', 1.0)
        mean_angle = node['mobility'].get('mean_angle', np.pi / 4)

        if 'prev_speed' not in node['mobility']:
            node['mobility']['prev_speed'] = float(speed) # FIX: Convert on first write
        if 'prev_angle' not in node['mobility']:
            node['mobility']['prev_angle'] = float(np.random.uniform(0, 2 * np.pi)) # FIX: Convert on first write

        prev_speed = node['mobility']['prev_speed']
        prev_angle = node['mobility']['prev_angle']

        rand_speed = np.random.normal(0, 0.2)
        rand_angle = np.random.normal(0, 0.3)

        new_speed = (
            alpha * prev_speed
            + (1 - alpha) * mean_speed
            + np.sqrt(1 - alpha**2) * rand_speed
        )
        new_angle = (
            alpha * prev_angle
            + (1 - alpha) * mean_angle
            + np.sqrt(1 - alpha**2) * rand_angle
        )

        node['mobility']['prev_speed'] = new_speed
        node['mobility']['prev_angle'] = new_angle

        dx = new_speed * np.cos(new_angle) * tau
        dy = new_speed * np.sin(new_angle) * tau
        
        new_location = location + np.array([dx, dy, 0])

        new_location[0] = min(max(0, new_location[0]), room_length)
        new_location[1] = min(max(0, new_location[1]), room_width)

        return new_location.tolist()


